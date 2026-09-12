import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession, Feedback, MessageCitation
from app.models.document import EMBEDDING_DIM, Chunk, Document, IngestionJob
from app.models.user import User
from app.quota import service as quota_service
from tests.conftest import TEST_PASSWORD


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _conversation(
    session: AsyncSession,
    user: User,
    *,
    question: str,
    answer: str,
    answered: bool,
    latency_ms: int,
) -> ChatMessage:
    chat_session = ChatSession(id=uuid.uuid4(), channel="widget", user_id=user.id)
    session.add(chat_session)
    await session.flush()

    session.add(ChatMessage(session_id=chat_session.id, role="user", content=question))
    await session.flush()

    assistant = ChatMessage(
        session_id=chat_session.id,
        role="assistant",
        content=answer,
        latency_ms=latency_ms,
        answered_from_context=answered,
    )
    session.add(assistant)
    await session.flush()
    return assistant


async def _document_with_chunk(session: AsyncSession, user: User, filename: str) -> Chunk:
    document = Document(
        id=uuid.uuid4(),
        owner_id=user.id,
        filename=filename,
        mime_type="application/pdf",
        storage_path=f"/data/uploads/{uuid.uuid4().hex}.pdf",
        size_bytes=1,
        status="ready",
        page_count=1,
    )
    session.add(document)
    await session.flush()

    chunk = Chunk(
        document_id=document.id,
        owner_id=user.id,
        ordinal=0,
        text="เนื้อหา",
        page_no=1,
        source="parse",
        embedding=[0.0] * EMBEDDING_DIM,
    )
    session.add(chunk)
    await session.flush()
    return chunk


async def test_overview_reports_latency_and_unanswered_ratio(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    await _conversation(
        session, admin, question="ถามได้", answer="ตอบได้", answered=True, latency_ms=1000
    )
    await _conversation(
        session, admin, question="ถามไม่ได้", answer="ไม่พบ", answered=False, latency_ms=3000
    )
    await session.commit()

    headers = await _auth(client, admin)
    body = (await client.get("/api/admin/analytics/overview", headers=headers)).json()

    assert body["messages"] == 2
    assert body["unanswered"] == 1
    assert body["unanswered_ratio"] == 0.5
    assert body["latency_ms"]["p50"] == 2000
    assert len(body["daily"]) == 1
    assert body["daily"][0]["messages"] == 2


async def test_overview_handles_no_data(client: AsyncClient, admin: User) -> None:
    """dashboard ต้องไม่พังตอนระบบยังไม่มีใครใช้ ซึ่งคือวันแรกของทุก deploy"""
    headers = await _auth(client, admin)
    body = (await client.get("/api/admin/analytics/overview", headers=headers)).json()

    assert body["messages"] == 0
    assert body["unanswered_ratio"] == 0.0
    assert body["latency_ms"]["p50"] is None
    assert body["feedback"]["negative_ratio"] == 0.0
    assert body["daily"] == []


async def test_feedback_ratio(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    good = await _conversation(
        session, admin, question="ก", answer="ข", answered=True, latency_ms=100
    )
    bad = await _conversation(
        session, admin, question="ค", answer="ง", answered=True, latency_ms=100
    )
    session.add(Feedback(message_id=good.id, rating=1))
    session.add(Feedback(message_id=bad.id, rating=-1))
    session.add(Feedback(message_id=bad.id, rating=-1))
    await session.commit()

    headers = await _auth(client, admin)
    body = (await client.get("/api/admin/analytics/overview", headers=headers)).json()

    assert body["feedback"] == {"up": 1, "down": 2, "negative_ratio": 0.667}


async def test_unanswered_list_pairs_answers_with_their_questions(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """เป็นไปได้เพราะ created_at ใช้ clock_timestamp() แล้ว — ถ้ากลับไปใช้ now() จะจับคู่มั่ว"""
    await _conversation(
        session, admin, question="ตอบได้", answer="คำตอบ", answered=True, latency_ms=100
    )
    await _conversation(
        session,
        admin,
        question="ระเบียบการเบิกค่าเดินทางเป็นอย่างไร",
        answer="ไม่พบข้อมูล",
        answered=False,
        latency_ms=100,
    )
    await session.commit()

    headers = await _auth(client, admin)
    rows = (await client.get("/api/admin/analytics/unanswered", headers=headers)).json()

    assert len(rows) == 1
    assert rows[0]["question"] == "ระเบียบการเบิกค่าเดินทางเป็นอย่างไร"


async def test_cited_documents_ranking(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    popular = await _document_with_chunk(session, admin, "คู่มือพนักงาน.pdf")
    rare = await _document_with_chunk(session, admin, "เอกสารเก่า.pdf")

    for _ in range(3):
        message = await _conversation(
            session, admin, question="ก", answer="ข", answered=True, latency_ms=100
        )
        session.add(
            MessageCitation(message_id=message.id, chunk_id=popular.id, score=0.9, rank=1)
        )
    message = await _conversation(
        session, admin, question="ค", answer="ง", answered=True, latency_ms=100
    )
    session.add(MessageCitation(message_id=message.id, chunk_id=rare.id, score=0.5, rank=1))
    await session.commit()

    headers = await _auth(client, admin)
    rows = (await client.get("/api/admin/analytics/documents", headers=headers)).json()

    assert [r["filename"] for r in rows] == ["คู่มือพนักงาน.pdf", "เอกสารเก่า.pdf"]
    assert rows[0]["citations"] == 3
    assert rows[0]["avg_score"] == pytest.approx(0.9, abs=1e-4)


async def test_ingestion_stats_derive_real_seconds_per_page(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """ค่านี้เอาไปแทน OCR_SECONDS_PER_PAGE เพื่อให้ ETA ที่โชว์ user แม่นขึ้น"""
    document = Document(
        id=uuid.uuid4(),
        owner_id=admin.id,
        filename="scan.pdf",
        mime_type="application/pdf",
        storage_path="/data/uploads/x.pdf",
        size_bytes=1,
        status="ready",
        page_count=10,
    )
    session.add(document)
    await session.flush()

    queued = datetime.now(UTC) - timedelta(minutes=30)
    session.add(
        IngestionJob(
            document_id=document.id,
            stage="done",
            pages_done=10,
            pages_total=10,
            gpu_seconds=220.0,
            queued_at=queued,
            started_at=queued + timedelta(seconds=60),
            finished_at=datetime.now(UTC),
        )
    )
    await session.commit()

    headers = await _auth(client, admin)
    body = (await client.get("/api/admin/analytics/ingestion", headers=headers)).json()

    assert body["jobs"] == 1
    assert body["pages_processed"] == 10
    assert body["seconds_per_page"] == 22.0
    assert body["queue_wait_p95_seconds"] == 60


async def test_quota_usage_lists_every_user_even_with_no_activity(
    client: AsyncClient, session: AsyncSession, user: User, admin: User
) -> None:
    document = Document(
        id=uuid.uuid4(),
        owner_id=user.id,
        filename="a.pdf",
        mime_type="application/pdf",
        storage_path="/data/uploads/a.pdf",
        size_bytes=1,
        page_count=12,
    )
    session.add(document)
    await session.flush()
    await quota_service.reserve(session, user, document.id, 12)
    await quota_service.commit(session, user, document.id, 12)
    await session.commit()

    headers = await _auth(client, admin)
    body = (await client.get("/api/admin/quota/usage", headers=headers)).json()

    by_email = {row["email"]: row for row in body["users"]}
    assert by_email[user.email]["pages"] == 12
    assert by_email[user.email]["documents"] == 1
    # admin ที่ยังไม่ได้อัปอะไรก็ต้องอยู่ในรายการ ไม่ใช่หายไป
    assert by_email[admin.email]["pages"] == 0
    assert by_email[admin.email]["unlimited"] is True


async def test_analytics_is_admin_only(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    for path in (
        "/api/admin/analytics/overview",
        "/api/admin/analytics/unanswered",
        "/api/admin/analytics/documents",
        "/api/admin/analytics/ingestion",
        "/api/admin/quota/usage",
    ):
        assert (await client.get(path, headers=headers)).status_code == 403, path
