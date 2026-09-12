import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import orchestrator
from app.llm.prompts import NO_CONTEXT_ANSWER
from app.models.chat import ChatMessage, MessageCitation
from app.models.document import EMBEDDING_DIM, Chunk, Document
from app.models.user import User
from tests.conftest import TEST_PASSWORD


def _vector(axis: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[axis] = 1.0
    return vec


class FakeEmbeddingClient:
    """คำถามทุกข้อ map ไปแกน 0 — ให้ chunk ที่วางไว้แกน 0 เป็นตัวที่ตรงที่สุด"""

    def __init__(self, axis: int = 0) -> None:
        self.axis = axis

    async def embed_one(self, text: str, **kwargs) -> list[float]:
        return _vector(self.axis)


class FakeChatClient:
    model_used = "fake-model"
    calls: list[list[dict]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def complete(self, messages, **kwargs) -> dict:
        FakeChatClient.calls.append(messages)
        return {
            "choices": [{"message": {"content": "พนักงานลาพักร้อนได้ปีละสิบวัน [1]"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 15},
        }

    async def stream(self, messages, **kwargs):
        FakeChatClient.calls.append(messages)
        for piece in ["พนักงาน", "ลาพักร้อนได้", "ปีละสิบวัน [1]"]:
            yield piece


@pytest.fixture(autouse=True)
def stub_models(monkeypatch):
    FakeChatClient.calls = []
    monkeypatch.setattr(orchestrator, "EmbeddingClient", FakeEmbeddingClient)
    monkeypatch.setattr(orchestrator, "ChatChain", FakeChatClient)
    return FakeChatClient


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_chunk(session: AsyncSession, user: User, text: str, axis: int) -> Document:
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
            text=text,
            page_no=3,
            token_count=20,
            source="parse",
            embedding=_vector(axis),
        )
    )
    await session.commit()
    return document


def _parse_sse(body: str) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next((l[7:] for l in lines if l.startswith("event: ")), None)
        data = next((l[6:] for l in lines if l.startswith("data: ")), None)
        if event and data is not None:
            events.append((event, data))
    return events


async def test_answer_streams_tokens_with_citations(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user, "พนักงานมีสิทธิลาพักร้อนปีละสิบวัน", axis=0)
    headers = await _auth(client, user)

    resp = await client.post(
        "/api/chat", headers=headers, json={"message": "ลาพักร้อนได้กี่วัน"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    names = [name for name, _ in events]
    assert names[0] == "session"
    assert "citations" in names
    assert names[-1] == "done"

    tokens = "".join(
        json.loads(data)["text"] for name, data in events if name == "token"
    )
    assert tokens == "พนักงานลาพักร้อนได้ปีละสิบวัน [1]"

    citations = json.loads(
        next(data for name, data in events if name == "citations")
    )["citations"]
    assert citations[0]["document_name"] == "คู่มือพนักงาน.pdf"
    assert citations[0]["page_no"] == 3
    assert citations[0]["rank"] == 1


async def test_no_relevant_context_never_calls_the_llm(
    client: AsyncClient, session: AsyncSession, user: User, stub_models
) -> None:
    """ตัดโอกาส hallucinate ทิ้ง และประหยัดเวลาบนการ์ดช้าไปพร้อมกัน"""
    await _seed_chunk(session, user, "เรื่องอื่นที่ไม่เกี่ยวเลย", axis=9)
    headers = await _auth(client, user)

    resp = await client.post("/api/chat", headers=headers, json={"message": "ลาพักร้อนได้กี่วัน"})
    events = _parse_sse(resp.text)

    tokens = "".join(
        json.loads(data)["text"] for name, data in events if name == "token"
    )
    assert tokens == NO_CONTEXT_ANSWER
    assert stub_models.calls == [], "ห้ามเรียก LLM เมื่อไม่มี context ที่ผ่านเกณฑ์"


async def test_unanswered_questions_are_flagged_for_analytics(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user, "เรื่องอื่น", axis=9)
    headers = await _auth(client, user)
    await client.post("/api/chat", headers=headers, json={"message": "ถามเรื่องที่ไม่มีในเอกสาร"})

    result = await session.execute(
        select(ChatMessage).where(ChatMessage.role == "assistant")
    )
    assistant = result.scalar_one()
    # คอลัมน์นี้คือสิ่งที่ทำให้ analytics ตอบได้ว่าคลังความรู้ยังขาดอะไร
    assert assistant.answered_from_context is False


async def test_conversation_is_logged_with_citations(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user, "พนักงานมีสิทธิลาพักร้อนปีละสิบวัน", axis=0)
    headers = await _auth(client, user)
    await client.post("/api/chat", headers=headers, json={"message": "ลาพักร้อนได้กี่วัน"})

    messages = (
        await session.execute(select(ChatMessage).order_by(ChatMessage.created_at))
    ).scalars().all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].latency_ms is not None

    citations = (await session.execute(select(MessageCitation))).scalars().all()
    assert len(citations) == 1
    assert citations[0].rank == 1


async def test_context_is_placed_closest_to_the_question(
    client: AsyncClient, session: AsyncSession, user: User, stub_models
) -> None:
    await _seed_chunk(session, user, "พนักงานมีสิทธิลาพักร้อนปีละสิบวัน", axis=0)
    headers = await _auth(client, user)
    await client.post("/api/chat", headers=headers, json={"message": "ลาพักร้อนได้กี่วัน"})

    messages = stub_models.calls[0]
    assert messages[0]["role"] == "system"
    # โมเดลเล็กให้น้ำหนักกับส่วนท้าย prompt มากกว่า context จึงต้องอยู่ติดคำถาม
    assert messages[-1]["role"] == "user"
    assert "<context>" in messages[-1]["content"]
    assert "ลาพักร้อนปีละสิบวัน" in messages[-1]["content"]


async def test_second_turn_reuses_the_same_session(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user, "พนักงานมีสิทธิลาพักร้อนปีละสิบวัน", axis=0)
    headers = await _auth(client, user)

    first = await client.post("/api/chat", headers=headers, json={"message": "คำถามแรก"})
    session_id = json.loads(_parse_sse(first.text)[0][1])["session_id"]

    second = await client.post(
        "/api/chat", headers=headers, json={"message": "คำถามที่สอง", "session_id": session_id}
    )
    assert json.loads(_parse_sse(second.text)[0][1])["session_id"] == session_id

    messages = (await session.execute(select(ChatMessage))).scalars().all()
    assert len(messages) == 4


async def test_users_cannot_retrieve_other_peoples_documents(
    client: AsyncClient, session: AsyncSession, user: User, admin: User
) -> None:
    await _seed_chunk(session, admin, "ความลับของคนอื่น", axis=0)
    headers = await _auth(client, user)

    resp = await client.post("/api/chat", headers=headers, json={"message": "ขอข้อมูลหน่อย"})
    events = _parse_sse(resp.text)
    tokens = "".join(
        json.loads(data)["text"] for name, data in events if name == "token"
    )
    assert tokens == NO_CONTEXT_ANSWER


async def test_feedback_is_recorded(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user, "พนักงานมีสิทธิลาพักร้อนปีละสิบวัน", axis=0)
    headers = await _auth(client, user)
    resp = await client.post("/api/chat", headers=headers, json={"message": "ลาพักร้อนได้กี่วัน"})

    done = json.loads(
        next(data for name, data in _parse_sse(resp.text) if name == "done")
    )
    feedback = await client.post(
        "/api/feedback",
        headers=headers,
        json={"message_id": done["message_id"], "rating": -1, "comment": "ยังไม่ตรงคำถาม"},
    )
    assert feedback.status_code == 204


async def test_chat_requires_authentication(client: AsyncClient) -> None:
    assert (await client.post("/api/chat", json={"message": "สวัสดี"})).status_code == 401
