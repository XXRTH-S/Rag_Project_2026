"""เทสการอ่านประวัติบทสนทนากลับมา

ทุกคำถาม-คำตอบถูกเขียนลง DB อยู่แล้วตั้งแต่แรก แต่เดิมไม่มีทางอ่านกลับ
refresh หน้าแชทแล้วบทสนทนาหายทั้งที่ข้อมูลยังอยู่ครบ
"""
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import orchestrator
from app.models.chat import MessageCitation
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

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def stream(self, messages, **kwargs):
        yield "พนักงานลาพักร้อนได้ปีละสิบวัน [1]"


@pytest.fixture(autouse=True)
def stub_models(monkeypatch):
    monkeypatch.setattr(orchestrator, "EmbeddingClient", FakeEmbeddingClient)
    monkeypatch.setattr(orchestrator, "ChatChain", FakeChatClient)


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_chunk(session: AsyncSession, user: User) -> Document:
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
            text="พนักงานมีสิทธิลาพักร้อนปีละสิบวัน",
            page_no=3,
            token_count=20,
            source="parse",
            embedding=_vector(0),
        )
    )
    await session.commit()
    return document


async def _ask(client: AsyncClient, headers: dict, message: str, session_id: str | None = None):
    """ถามหนึ่งคำถาม แล้วคืน (session_id, message_id)"""
    body: dict = {"message": message}
    if session_id:
        body["session_id"] = session_id
    resp = await client.post("/api/chat", headers=headers, json=body)
    assert resp.status_code == 200
    sid = mid = None
    for block in resp.text.strip().split("\n\n"):
        lines = block.splitlines()
        name = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if not data:
            continue
        payload = json.loads(data)
        if name == "session":
            sid = payload["session_id"]
        elif name == "done":
            mid = payload.get("message_id")
    return sid, mid


async def test_new_conversation_appears_in_the_list(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user)
    headers = await _auth(client, user)
    sid, _ = await _ask(client, headers, "ลาพักร้อนได้กี่วัน")

    resp = await client.get("/api/chat/sessions", headers=headers)
    assert resp.status_code == 200
    rows = resp.json()["items"]
    assert len(rows) == 1
    assert rows[0]["id"] == sid
    # หัวข้อมาจากคำถามแรก ไม่ใช่คอลัมน์ที่ต้อง migrate เพิ่ม
    assert rows[0]["title"] == "ลาพักร้อนได้กี่วัน"
    assert rows[0]["message_count"] == 2


async def test_long_question_is_trimmed_for_the_title(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """หัวข้อยาวกว่าแถบข้างต้องถูกตัด ไม่ใช่ปล่อยให้ดันความกว้างของ layout"""
    await _seed_chunk(session, user)
    headers = await _auth(client, user)
    await _ask(client, headers, "ก" * 200)

    rows = (await client.get("/api/chat/sessions", headers=headers)).json()["items"]
    assert len(rows[0]["title"]) < 200
    assert rows[0]["title"].endswith("…")


async def test_history_returns_messages_citations_and_feedback(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user)
    headers = await _auth(client, user)
    sid, mid = await _ask(client, headers, "ลาพักร้อนได้กี่วัน")
    await client.post("/api/feedback", headers=headers, json={"message_id": mid, "rating": 1})

    body = (await client.get(f"/api/chat/sessions/{sid}", headers=headers)).json()
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"], "ลำดับต้องเป็นถามก่อนตอบ"

    question, answer = body["messages"]
    assert question["citations"] == [], "คำถามของผู้ใช้ไม่มีที่มา"
    assert answer["content"] == "พนักงานลาพักร้อนได้ปีละสิบวัน [1]"
    assert answer["citations"][0]["document_name"] == "คู่มือพนักงาน.pdf"
    assert answer["citations"][0]["page_no"] == 3
    # ถ้าไม่คืน feedback มาด้วย ปุ่มให้คะแนนจะกลับมากดได้ใหม่ทุกครั้งที่เปิดประวัติ
    assert answer["feedback"] == 1
    assert question["feedback"] is None


async def test_latest_rating_wins(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """ตาราง feedback ไม่ได้บังคับ unique ต่อข้อความ กดซ้ำได้หลายครั้ง
    ครั้งล่าสุดต้องเป็นคำตัดสิน ตรงกับที่ผู้ใช้เข้าใจว่ากดใหม่แล้วทับของเก่า
    """
    await _seed_chunk(session, user)
    headers = await _auth(client, user)
    sid, mid = await _ask(client, headers, "ลาพักร้อนได้กี่วัน")
    await client.post("/api/feedback", headers=headers, json={"message_id": mid, "rating": 1})
    await client.post("/api/feedback", headers=headers, json={"message_id": mid, "rating": -1})

    body = (await client.get(f"/api/chat/sessions/{sid}", headers=headers)).json()
    assert body["messages"][1]["feedback"] == -1


async def test_conversation_continues_in_the_same_session(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user)
    headers = await _auth(client, user)
    sid, _ = await _ask(client, headers, "ลาพักร้อนได้กี่วัน")
    sid2, _ = await _ask(client, headers, "แล้วสะสมข้ามปีได้ไหม", session_id=sid)
    assert sid2 == sid

    rows = (await client.get("/api/chat/sessions", headers=headers)).json()["items"]
    assert len(rows) == 1, "ถามต่อใน session เดิมต้องไม่สร้างบทสนทนาใหม่"
    assert rows[0]["message_count"] == 4


async def test_citations_survive_the_chunk_being_deleted(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """เหตุผลทั้งหมดของ migration 0004

    การสั่ง reprocess ลบ chunk เก่าทั้งหมดก่อนสร้างใหม่ ซึ่งเป็นการใช้งานปกติ
    เดิม chunk_id ผูก CASCADE แถวอ้างอิงจึงหายทั้งแถว คำตอบเก่าเหลือแต่ข้อความ
    ไม่มีที่มา ซึ่งขัดกับหลักที่ว่าทุกคำตอบต้องตรวจย้อนได้
    """
    document = await _seed_chunk(session, user)
    headers = await _auth(client, user)
    sid, _ = await _ask(client, headers, "ลาพักร้อนได้กี่วัน")

    await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
    await session.commit()

    body = (await client.get(f"/api/chat/sessions/{sid}", headers=headers)).json()
    citation = body["messages"][1]["citations"][0]
    assert citation["document_name"] == "คู่มือพนักงาน.pdf", "ชื่อเอกสารต้องยังอยู่"
    assert citation["page_no"] == 3

    rows = (await session.execute(select(MessageCitation))).scalars().all()
    assert len(rows) == 1, "แถวอ้างอิงต้องไม่ถูกลบตาม chunk"
    assert rows[0].chunk_id is None, "chunk_id ควรถูกล้างเป็น NULL ไม่ใช่ลบทั้งแถว"


async def test_other_users_history_is_invisible(
    client: AsyncClient, session: AsyncSession, user: User, admin: User
) -> None:
    """ตอบ 404 ไม่ใช่ 403 เพราะ 403 เท่ากับยืนยันว่า id นี้มีจริง
    ทำให้ไล่เดา id ของคนอื่นได้ว่ามีอยู่หรือไม่
    """
    await _seed_chunk(session, user)
    headers = await _auth(client, user)
    sid, _ = await _ask(client, headers, "ลาพักร้อนได้กี่วัน")

    other = await _auth(client, admin)
    assert (await client.get(f"/api/chat/sessions/{sid}", headers=other)).status_code == 404
    assert (await client.get("/api/chat/sessions", headers=other)).json()["items"] == []
    # admin ก็ลบของคนอื่นไม่ได้ — ไม่ใช่เรื่องสิทธิ์ แต่บทสนทนาเป็นเรื่องส่วนตัว
    assert (await client.delete(f"/api/chat/sessions/{sid}", headers=other)).status_code == 404


async def test_delete_removes_the_conversation_and_its_messages(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_chunk(session, user)
    headers = await _auth(client, user)
    sid, _ = await _ask(client, headers, "ลาพักร้อนได้กี่วัน")

    assert (await client.delete(f"/api/chat/sessions/{sid}", headers=headers)).status_code == 204
    assert (await client.get(f"/api/chat/sessions/{sid}", headers=headers)).status_code == 404
    assert (await client.get("/api/chat/sessions", headers=headers)).json()["items"] == []
    # ข้อความและที่มาต้องหายตามไปด้วย ไม่ใช่ค้างเป็นขยะที่เข้าถึงไม่ได้
    assert (await session.execute(select(MessageCitation))).scalars().all() == []


async def test_unknown_session_is_404(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    resp = await client.get(f"/api/chat/sessions/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


async def test_history_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/api/chat/sessions")).status_code == 401
