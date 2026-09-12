"""เทสการกู้เอกสารที่ job ค้างคิวจนสั่งประมวลผลใหม่ไม่ได้

ที่มา: worker พังกลางทาง (เช่น connection pool ข้าม event loop) แล้วแถวงาน
ค้างอยู่ที่ stage="queued" ตลอดไป เพราะไม่มีใครมาปิดให้ · reprocess ตอบ 409 ทุกครั้ง
แต่ chunk ถูกลบไปแล้วตั้งแต่ครั้งก่อน เอกสารจึงค้นไม่เจอและซ่อมผ่าน API ไม่ได้เลย
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion import queue as ingest_queue
from app.models.document import Document, IngestionJob
from app.models.user import User
from tests.conftest import TEST_PASSWORD


@pytest.fixture(autouse=True)
def stub_queue(monkeypatch):
    """ไม่ต้องมี Redis/Celery จริง — เทสนี้สนใจแค่เงื่อนไขว่ารับงานใหม่หรือไม่"""
    monkeypatch.setattr(ingest_queue, "enqueue_ingestion", lambda *a, **k: "fake-task-id")


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _document_with_job(
    session: AsyncSession,
    owner: User,
    tmp_path,
    *,
    queued_minutes_ago: float,
    started: bool,
) -> tuple[Document, IngestionJob]:
    source = tmp_path / f"{uuid.uuid4().hex}.txt"
    source.write_text("ระเบียบบริษัท", encoding="utf-8")

    document = Document(
        id=uuid.uuid4(),
        owner_id=owner.id,
        filename="ระเบียบ.txt",
        mime_type="text/plain",
        storage_path=str(source),
        size_bytes=source.stat().st_size,
        status="processing",
        page_count=1,
    )
    session.add(document)
    await session.flush()

    queued_at = datetime.now(UTC) - timedelta(minutes=queued_minutes_ago)
    job = IngestionJob(
        document_id=document.id,
        stage="queued",
        pages_total=1,
        queue=ingest_queue.QUEUE_ADMIN,
        queued_at=queued_at,
        started_at=queued_at if started else None,
    )
    session.add(job)
    await session.commit()
    return document, job


async def test_job_stuck_in_queue_can_be_reclaimed(
    client: AsyncClient, session: AsyncSession, admin: User, tmp_path
) -> None:
    """ไม่เคยเริ่ม + รอนานเกินเกณฑ์ = worker ตาย ต้องปล่อยให้สั่งใหม่ได้"""
    document, job = await _document_with_job(
        session,
        admin,
        tmp_path,
        queued_minutes_ago=settings.ingestion_stale_after_minutes + 1,
        started=False,
    )
    headers = await _auth(client, admin)

    resp = await client.post(
        f"/api/admin/documents/{document.id}/reprocess", headers=headers, json={}
    )
    assert resp.status_code == 202, resp.text

    await session.refresh(job)
    assert job.stage == "failed", "งานเก่าต้องถูกปิด ไม่ใช่ค้างคู่กับงานใหม่"
    assert "worker" in (job.error or ""), "ต้องบอกสาเหตุไว้ ไม่ใช่ปิดเงียบ ๆ"


async def test_job_still_within_the_window_is_left_alone(
    client: AsyncClient, session: AsyncSession, admin: User, tmp_path
) -> None:
    """คิวยาวไม่ใช่คิวตาย — งานที่เพิ่งเข้าคิวต้องไม่ถูกแย่งไปทำใหม่"""
    document, _ = await _document_with_job(
        session, admin, tmp_path, queued_minutes_ago=1, started=False
    )
    headers = await _auth(client, admin)

    resp = await client.post(
        f"/api/admin/documents/{document.id}/reprocess", headers=headers, json={}
    )
    assert resp.status_code == 409


async def test_job_that_actually_started_is_never_reclaimed(
    client: AsyncClient, session: AsyncSession, admin: User, tmp_path
) -> None:
    """งานที่เริ่มแล้วอาจกำลังทำอยู่จริง — 500 หน้าใช้เวลาเกินชั่วโมง
    แยกจากงานที่ค้างไม่ได้ถ้าไม่มี heartbeat จึงต้องไม่ไปยุ่งกับมัน
    """
    document, job = await _document_with_job(
        session,
        admin,
        tmp_path,
        queued_minutes_ago=settings.ingestion_stale_after_minutes * 10,
        started=True,
    )
    headers = await _auth(client, admin)

    resp = await client.post(
        f"/api/admin/documents/{document.id}/reprocess", headers=headers, json={}
    )
    assert resp.status_code == 409

    await session.refresh(job)
    assert job.stage == "queued", "ห้ามปิดงานที่อาจกำลังเดินอยู่"
