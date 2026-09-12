"""เทสพฤติกรรมเมื่อเรียก LLM ไม่ได้

ระบบต้องยังใช้งานได้แม้โมเดลตอบคำถามยังไม่พร้อม — ยกข้อความจากเอกสารมาให้แทน
ดีกว่าโยน HTTP error ดิบใส่ผู้ใช้ และทำให้ POC สาธิตได้ตั้งแต่ก่อนโมเดลโหลดเสร็จ
"""
import json
import uuid

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm import orchestrator
from app.llm.prompts import MODEL_UNAVAILABLE_NOTICE
from app.models.chat import ChatMessage
from app.models.document import EMBEDDING_DIM, Chunk, Document
from app.models.user import User
from tests.conftest import TEST_PASSWORD


def _vector(axis: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[axis] = 1.0
    return vec


class FakeEmbeddingClient:
    async def embed_one(self, text: str, **kwargs) -> list[float]:
        return _vector(0)


class BrokenChatClient:
    """จำลอง Ollama ที่ยังไม่ได้ pull โมเดล — ตอบ 404"""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def stream(self, messages, **kwargs):
        raise httpx.HTTPStatusError(
            "404 Not Found",
            request=httpx.Request("POST", "http://ollama:11434/v1/chat/completions"),
            response=httpx.Response(404),
        )
        yield ""  # pragma: no cover


@pytest.fixture(autouse=True)
def stub_models(monkeypatch):
    monkeypatch.setattr(orchestrator, "EmbeddingClient", FakeEmbeddingClient)
    monkeypatch.setattr(orchestrator, "ChatChain", BrokenChatClient)


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed(session: AsyncSession, user: User) -> None:
    document = Document(
        id=uuid.uuid4(),
        owner_id=user.id,
        filename="คู่มือพนักงาน.pdf",
        mime_type="application/pdf",
        storage_path=f"/data/uploads/{uuid.uuid4().hex}.pdf",
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
            text="[คู่มือ · ระเบียบการลา]\nพนักงานมีสิทธิลาพักร้อนปีละสิบวันทำการ",
            page_no=4,
            source="parse",
            embedding=_vector(0),
        )
    )
    await session.commit()


def _tokens(body: str) -> str:
    out = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next((l[7:] for l in lines if l.startswith("event: ")), None)
        data = next((l[6:] for l in lines if l.startswith("data: ")), None)
        if event == "token" and data:
            out.append(json.loads(data)["text"])
    return "".join(out)


async def test_falls_back_to_excerpts_when_llm_is_unavailable(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed(session, user)
    headers = await _auth(client, user)

    resp = await client.post("/api/chat", headers=headers, json={"message": "ลาพักร้อนกี่วัน"})
    text = _tokens(resp.text)

    assert MODEL_UNAVAILABLE_NOTICE in text
    assert "ลาพักร้อนปีละสิบวัน" in text
    assert "คู่มือพนักงาน.pdf" in text
    assert "หน้า 4" in text
    # ต้องไม่มี HTTP error ดิบหลุดไปถึงผู้ใช้
    assert "404" not in text
    assert "http://" not in text


async def test_fallback_strips_the_context_prefix(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """prefix บริบทที่ chunker ใส่ไว้เป็นเรื่องภายใน ผู้ใช้ไม่ต้องเห็น"""
    await _seed(session, user)
    headers = await _auth(client, user)

    resp = await client.post("/api/chat", headers=headers, json={"message": "ลาพักร้อนกี่วัน"})
    assert "[คู่มือ · ระเบียบการลา]" not in _tokens(resp.text)


async def test_fallback_is_recorded_without_a_model_name(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """analytics ต้องแยกออกว่าคำตอบไหนมาจากโมเดลจริง ไหนมาจาก fallback"""
    await _seed(session, user)
    headers = await _auth(client, user)
    await client.post("/api/chat", headers=headers, json={"message": "ลาพักร้อนกี่วัน"})

    assistant = (
        await session.execute(select(ChatMessage).where(ChatMessage.role == "assistant"))
    ).scalar_one()
    assert assistant.model is None
    # context หาเจอจริง แค่ขั้นเรียบเรียงที่ล้ม
    assert assistant.answered_from_context is True


async def test_fallback_can_be_disabled(
    client: AsyncClient, session: AsyncSession, user: User, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "llm_fallback_to_excerpts", False)
    await _seed(session, user)
    headers = await _auth(client, user)

    resp = await client.post("/api/chat", headers=headers, json={"message": "ลาพักร้อนกี่วัน"})
    # router จับ exception แล้วส่งเป็น event error แทนที่จะเงียบ
    assert "event: error" in resp.text
