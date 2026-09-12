"""เทสว่าคำตอบแบบ "ไม่รู้" ถูกนับเป็นช่องว่างของคลังความรู้

analytics ตอบคำถามว่า "คลังยังขาดเรื่องอะไร" จากธง answered_from_context เท่านั้น
เดิมธงนี้เป็น True เสมอเมื่อ retrieval หา chunk เจอ แม้โมเดลจะตอบว่าไม่พบข้อมูลก็ตาม
รายงานจึงมองไม่เห็นคำถามกลุ่มที่ "ค้นเจอของใกล้เคียงแต่ตอบไม่ได้"

กลุ่มนี้กลายเป็นเส้นทางหลักเมื่อคลังมีหลายหมวด — ถามเรื่อง Rust แล้วไปเจอ chunk
เรื่องตัวแปรของ Go ซึ่งคะแนนสูงพอจะผ่านเกณฑ์ แต่ไม่มีคำตอบอยู่จริง
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import orchestrator
from app.llm.prompts import NO_CONTEXT_ANSWER, looks_like_refusal
from app.models.chat import ChatMessage
from app.models.document import EMBEDDING_DIM, Chunk, Document
from app.models.user import User
from tests.conftest import TEST_PASSWORD


def _vector(axis: int = 0) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[axis] = 1.0
    return vec


class FakeEmbeddingClient:
    async def embed_one(self, text: str, **kwargs) -> list[float]:
        return _vector()


class RefusingChatClient:
    """โมเดลที่หา chunk เจอ แต่อ่านแล้วตอบว่าไม่มีคำตอบในนั้น"""

    model_used = "fake-model"
    reply = NO_CONTEXT_ANSWER

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def stream(self, messages, **kwargs):
        yield type(self).reply

    async def complete(self, messages, **kwargs) -> dict:
        return {"choices": [{"message": {"content": type(self).reply}}], "usage": {}}


@pytest.fixture(autouse=True)
def stub_models(monkeypatch):
    RefusingChatClient.reply = NO_CONTEXT_ANSWER
    monkeypatch.setattr(orchestrator, "EmbeddingClient", FakeEmbeddingClient)
    monkeypatch.setattr(orchestrator, "ChatChain", RefusingChatClient)


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_chunk(session: AsyncSession, user: User) -> None:
    document = Document(
        id=uuid.uuid4(),
        owner_id=user.id,
        filename="go-เบื้องต้น.md",
        mime_type="text/markdown",
        storage_path=f"/data/uploads/{uuid.uuid4().hex}.md",
        size_bytes=1,
        status="ready",
        page_count=1,
    )
    session.add(document)
    await session.flush()
    session.add(
        Chunk(
            document_id=document.id,
            owner_id=user.id,
            ordinal=0,
            text="ประกาศตัวแปรใน Go ด้วยเครื่องหมาย := โดยให้ภาษาเดาชนิดเอง",
            page_no=1,
            token_count=20,
            source="parse",
            embedding=_vector(),
        )
    )
    await session.commit()


def _events(body: str) -> list[tuple[str, str]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        name = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if name and data is not None:
            out.append((name, data))
    return out


def test_paraphrased_refusal_is_still_detected() -> None:
    """โมเดล 4B ตัดคำท้ายทิ้งบ้าง เจอจริง "ในเอกสารที่มีครับ" แทน "ในเอกสารที่มีอยู่ครับ"
    ถ้าเทียบทั้งประโยคแบบตรงตัวจะพลาดเคสนี้
    """
    assert looks_like_refusal("ไม่พบข้อมูลนี้ในเอกสารที่มีครับ")
    assert looks_like_refusal(NO_CONTEXT_ANSWER)
    assert not looks_like_refusal("ประกาศตัวแปรใน Go ด้วย := ครับ [1]")


async def test_model_refusal_marks_the_answer_as_a_gap(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user)
    headers = await _auth(client, user)

    resp = await client.post("/api/chat", headers=headers, json={"message": "Rust ประกาศตัวแปรอย่างไร"})
    assert resp.status_code == 200

    done = next(data for name, data in _events(resp.text) if name == "done")
    assert json.loads(done)["answered_from_context"] is False, (
        "โมเดลตอบว่าไม่รู้ แต่ระบบยังรายงานว่าตอบจากเอกสารได้"
    )

    stored = (
        (
            await session.execute(
                select(ChatMessage).where(ChatMessage.role == "assistant")
            )
        )
        .scalars()
        .all()
    )
    assert [m.answered_from_context for m in stored] == [False]


async def test_real_answer_is_not_marked_as_a_gap(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """ต้องไม่เหวี่ยงไปอีกทาง — คำตอบที่ใช้ได้ต้องไม่ถูกนับเป็นช่องว่าง"""
    RefusingChatClient.reply = "ประกาศตัวแปรใน Go ด้วยเครื่องหมาย := ครับ [1]"
    await _seed_chunk(session, user)
    headers = await _auth(client, user)

    resp = await client.post("/api/chat", headers=headers, json={"message": "Go ประกาศตัวแปรอย่างไร"})
    done = next(data for name, data in _events(resp.text) if name == "done")
    assert json.loads(done)["answered_from_context"] is True


async def test_refused_question_shows_up_in_the_unanswered_report(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """เหตุผลทั้งหมดของการแก้นี้ — admin ต้องเห็นว่าคลังขาดเรื่องอะไร"""
    await _seed_chunk(session, admin)
    headers = await _auth(client, admin)
    await client.post("/api/chat", headers=headers, json={"message": "Rust ประกาศตัวแปรอย่างไร"})

    report = await client.get("/api/admin/analytics/unanswered", headers=headers)
    assert report.status_code == 200
    questions = json.dumps(report.json(), ensure_ascii=False)
    assert "Rust" in questions, f"คำถามที่ตอบไม่ได้ไม่ขึ้นในรายงาน: {questions[:300]}"
