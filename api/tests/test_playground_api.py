import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import orchestrator
from app.models.chat import PromptConfig
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


class FakeChatClient:
    model_used = "fake-model"
    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def complete(self, messages, **kwargs) -> dict:
        FakeChatClient.calls.append({"messages": messages, "kwargs": kwargs})
        return {
            "choices": [{"message": {"content": "คำตอบจากโมเดล [1]"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        }


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


async def _seed(session: AsyncSession, owner: User, text: str, axis: int) -> None:
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
            text=text,
            page_no=2,
            source="ocr",
            embedding=_vector(axis),
        )
    )
    await session.commit()


async def test_query_returns_raw_chunks_with_scores(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """เวลาคำตอบผิด ต้องแยกออกว่า retrieval พลาดหรือโมเดลตอบเพี้ยน"""
    await _seed(session, admin, "พนักงานลาพักร้อนได้ปีละสิบวัน", axis=0)
    headers = await _auth(client, admin)

    body = (
        await client.post(
            "/api/admin/playground/query", headers=headers, json={"message": "ลาพักร้อนกี่วัน"}
        )
    ).json()

    assert body["answer"] == "คำตอบจากโมเดล [1]"
    assert len(body["hits"]) == 1
    hit = body["hits"][0]
    assert hit["text"] == "พนักงานลาพักร้อนได้ปีละสิบวัน"
    assert hit["score"] > 0.99
    assert hit["page_no"] == 2
    assert hit["source"] == "ocr"


async def test_retrieval_only_mode_skips_the_llm(
    client: AsyncClient, session: AsyncSession, admin: User, stub_models
) -> None:
    """ทดลอง retrieval ได้เร็วโดยไม่ต้องรอ GPU ซึ่งบนการ์ดนี้ต่างกันหลายสิบวินาที"""
    await _seed(session, admin, "เนื้อหา", axis=0)
    headers = await _auth(client, admin)

    body = (
        await client.post(
            "/api/admin/playground/query",
            headers=headers,
            json={"message": "คำถาม", "call_llm": False},
        )
    ).json()

    assert len(body["hits"]) == 1
    assert body["answer"] is None
    assert stub_models.calls == []


async def test_min_score_override_is_applied(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    await _seed(session, admin, "ไม่เกี่ยวกับคำถาม", axis=7)
    headers = await _auth(client, admin)

    strict = (
        await client.post(
            "/api/admin/playground/query",
            headers=headers,
            json={"message": "คำถาม", "call_llm": False, "min_score": 0.35},
        )
    ).json()
    loose = (
        await client.post(
            "/api/admin/playground/query",
            headers=headers,
            json={"message": "คำถาม", "call_llm": False, "min_score": -1.0},
        )
    ).json()

    assert strict["hits"] == []
    assert len(loose["hits"]) == 1


async def test_admin_sees_documents_owned_by_others(
    client: AsyncClient, session: AsyncSession, admin: User, user: User
) -> None:
    await _seed(session, user, "เอกสารของ user ธรรมดา", axis=0)
    headers = await _auth(client, admin)

    body = (
        await client.post(
            "/api/admin/playground/query",
            headers=headers,
            json={"message": "คำถาม", "call_llm": False},
        )
    ).json()
    assert len(body["hits"]) == 1


async def test_playground_conversations_are_tagged_separately(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """ต้องแยก channel ออกจาก widget ไม่งั้นสถิติ latency จะปนกับการใช้งานจริง"""
    from app.models.chat import ChatSession

    await _seed(session, admin, "เนื้อหา", axis=0)
    headers = await _auth(client, admin)
    await client.post(
        "/api/admin/playground/query", headers=headers, json={"message": "คำถาม"}
    )

    sessions = (await session.execute(select(ChatSession))).scalars().all()
    assert [s.channel for s in sessions] == ["playground"]


async def test_activating_a_config_deactivates_the_previous_one(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """DB มี unique index บน (is_active) WHERE is_active — ต้องปิดตัวเดิมก่อนเปิดตัวใหม่"""
    headers = await _auth(client, admin)

    first = (
        await client.post(
            "/api/admin/prompt-configs",
            headers=headers,
            json={"name": "v1", "system_prompt": "prompt หนึ่ง"},
        )
    ).json()
    second = (
        await client.post(
            "/api/admin/prompt-configs",
            headers=headers,
            json={"name": "v2", "system_prompt": "prompt สอง", "top_k": 4},
        )
    ).json()

    assert (
        await client.post(f"/api/admin/prompt-configs/{first['id']}/activate", headers=headers)
    ).status_code == 200
    resp = await client.post(
        f"/api/admin/prompt-configs/{second['id']}/activate", headers=headers
    )
    assert resp.status_code == 200, resp.text

    configs = (await session.execute(select(PromptConfig))).scalars().all()
    active = [c for c in configs if c.is_active]
    assert len(active) == 1
    assert active[0].name == "v2"


async def test_active_config_drives_the_chat_endpoint(
    client: AsyncClient, session: AsyncSession, admin: User, stub_models
) -> None:
    await _seed(session, admin, "เนื้อหาที่เกี่ยวข้อง", axis=0)
    headers = await _auth(client, admin)

    created = (
        await client.post(
            "/api/admin/prompt-configs",
            headers=headers,
            json={"name": "custom", "system_prompt": "ตอบเป็นภาษาอังกฤษเท่านั้น", "top_k": 3},
        )
    ).json()
    await client.post(f"/api/admin/prompt-configs/{created['id']}/activate", headers=headers)

    await client.post(
        "/api/admin/playground/query", headers=headers, json={"message": "คำถาม"}
    )

    system_message = stub_models.calls[0]["messages"][0]
    assert system_message["content"] == "ตอบเป็นภาษาอังกฤษเท่านั้น"


async def test_playground_is_admin_only(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    resp = await client.post(
        "/api/admin/playground/query", headers=headers, json={"message": "คำถาม"}
    )
    assert resp.status_code == 403
    assert (await client.get("/api/admin/prompt-configs", headers=headers)).status_code == 403
