"""เทสบั๊กสองตัวที่เจอใน Playground

1. ตอบ 500 เมื่อ LLM ล่ม ทั้งที่ /api/chat ลดระดับอย่างนุ่มนวลได้
2. ค้นหาสองรอบ ทำให้ chunk ที่โชว์อาจไม่ใช่ชุดเดียวกับที่ส่งให้ LLM
"""
import uuid

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import orchestrator
from app.llm.prompts import MODEL_UNAVAILABLE_NOTICE
from app.models.document import EMBEDDING_DIM, Chunk, Document
from app.models.user import User
from tests.conftest import TEST_PASSWORD


def _vector(axis: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[axis] = 1.0
    return vec


class CountingEmbeddingClient:
    calls = 0

    async def embed_one(self, text: str, **kwargs) -> list[float]:
        CountingEmbeddingClient.calls += 1
        return _vector(0)


class WorkingChatClient:
    model_used = "fake-model"

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def complete(self, messages, **kwargs) -> dict:
        return {"choices": [{"message": {"content": "คำตอบ [1]"}}], "usage": {}}


class BrokenChatClient:
    model_used = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def complete(self, messages, **kwargs) -> dict:
        raise httpx.ConnectError("ต่อ LLM ไม่ได้")


@pytest.fixture(autouse=True)
def reset_counter(monkeypatch):
    CountingEmbeddingClient.calls = 0
    monkeypatch.setattr(orchestrator, "EmbeddingClient", CountingEmbeddingClient)


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed(session: AsyncSession, owner: User) -> None:
    document = Document(
        id=uuid.uuid4(),
        owner_id=owner.id,
        filename="คู่มือ.pdf",
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
            owner_id=owner.id,
            ordinal=0,
            text="พนักงานลาพักร้อนได้ปีละสิบวัน",
            page_no=2,
            source="parse",
            embedding=_vector(0),
        )
    )
    await session.commit()


async def test_playground_degrades_instead_of_500_when_llm_is_down(
    client: AsyncClient, session: AsyncSession, admin: User, monkeypatch
) -> None:
    monkeypatch.setattr(orchestrator, "ChatChain", BrokenChatClient)
    await _seed(session, admin)
    headers = await _auth(client, admin)

    resp = await client.post(
        "/api/admin/playground/query", headers=headers, json={"message": "ลาพักร้อนกี่วัน"}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert MODEL_UNAVAILABLE_NOTICE in body["answer"]
    # chunk ที่ค้นเจอต้องยังแสดงให้ admin เห็นตามปกติ
    assert len(body["hits"]) == 1


async def test_playground_retrieves_only_once(
    client: AsyncClient, session: AsyncSession, admin: User, monkeypatch
) -> None:
    """ค้นซ้ำสองรอบทำให้ chunk ที่โชว์อาจไม่ใช่ชุดที่ส่งให้ LLM จริง"""
    monkeypatch.setattr(orchestrator, "ChatChain", WorkingChatClient)
    await _seed(session, admin)
    headers = await _auth(client, admin)

    await client.post(
        "/api/admin/playground/query", headers=headers, json={"message": "ลาพักร้อนกี่วัน"}
    )

    assert CountingEmbeddingClient.calls == 1, (
        f"ควร embed คำถามครั้งเดียว แต่เรียกไป {CountingEmbeddingClient.calls} ครั้ง"
    )


async def test_retrieval_only_mode_does_not_embed_twice_either(
    client: AsyncClient, session: AsyncSession, admin: User, monkeypatch
) -> None:
    monkeypatch.setattr(orchestrator, "ChatChain", WorkingChatClient)
    await _seed(session, admin)
    headers = await _auth(client, admin)

    await client.post(
        "/api/admin/playground/query",
        headers=headers,
        json={"message": "ลาพักร้อนกี่วัน", "call_llm": False},
    )
    assert CountingEmbeddingClient.calls == 1
