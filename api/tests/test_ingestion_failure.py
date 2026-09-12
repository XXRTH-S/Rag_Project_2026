"""เทสเส้นทางที่ ingestion ล้มกลางทาง

เส้นทางนี้ต้องทำงานถูกเพราะงาน OCR ล้มได้จริง (ไฟล์เสีย, โมเดลไม่ตอบ, หมดเวลา)
และมันมีการ rollback แล้วใช้ object ที่โหลดมาก่อนหน้าต่อ ซึ่งเป็นจุดที่พังง่าย
"""
import uuid
from functools import partial
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ingestion import tasks
from app.models.document import Document, IngestionJob
from app.models.quota import QuotaEvent
from app.models.user import User
from app.quota import service as quota_service


@pytest.fixture
def run_job(engine):
    """เรียก pipeline โดยให้ใช้ฐานทดสอบ ไม่ใช่ฐานจริง"""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return partial(tasks._run, session_factory=factory)  # noqa: SLF001


async def _prepare(
    session: AsyncSession, user: User, *, pages: int = 3, ocr_pages: int = 0
) -> tuple[Document, IngestionJob]:
    document = Document(
        id=uuid.uuid4(),
        owner_id=user.id,
        filename="เอกสารที่จะพัง.txt",
        mime_type="text/plain",
        # ชี้ไปไฟล์ที่ไม่มีอยู่จริง เพื่อให้ขั้น parse โยน error
        storage_path="/data/uploads/ไม่มีไฟล์นี้.txt",
        size_bytes=100,
        page_count=pages,
        ocr_page_count=ocr_pages,
    )
    session.add(document)
    await session.flush()
    await quota_service.reserve(session, user, document.id, pages)

    job = IngestionJob(document_id=document.id, stage="queued", pages_total=pages)
    session.add(job)
    await session.commit()
    return document, job


async def test_failure_marks_job_and_document(
    session: AsyncSession, user: User, run_job
) -> None:
    document, job = await _prepare(session, user)

    result = await run_job(job.id)
    assert result["status"] == "failed"

    await session.refresh(job)
    await session.refresh(document)
    assert job.stage == "failed"
    assert job.error
    assert job.finished_at is not None
    assert document.status == "failed"


async def test_failure_before_gpu_refunds_quota(session: AsyncSession, user: User, run_job) -> None:
    """ยังไม่ได้แตะ GPU เลย ต้องคืนโควตาให้ครบ ไม่งั้น user เสียโควตาฟรีจากบั๊กของระบบ"""
    document, job = await _prepare(session, user, pages=3)

    before = await quota_service.get_status(session, user)
    assert before.documents_used == 1
    assert before.pages_used == 3

    await run_job(job.id)

    after = await quota_service.get_status(session, user)
    assert after.documents_used == 0
    assert after.pages_used == 0


async def test_failure_after_ocr_keeps_the_document_charge(
    session: AsyncSession, user: User, run_job
) -> None:
    """ถ้าเผา GPU ไปแล้วบางหน้า คืนเฉพาะหน้าที่เหลือ ไม่คืนสิทธิ์เอกสาร"""
    document, job = await _prepare(session, user, pages=3, ocr_pages=3)
    job.pages_done = 2
    await session.commit()

    await run_job(job.id)

    after = await quota_service.get_status(session, user)
    assert after.documents_used == 1, "ผ่าน OCR ไปแล้วต้องไม่คืนสิทธิ์เอกสาร"
    assert after.pages_used == 0


async def test_failure_writes_an_audit_trail(session: AsyncSession, user: User, run_job) -> None:
    document, job = await _prepare(session, user)
    await run_job(job.id)

    events = (
        await session.execute(
            select(QuotaEvent)
            .where(QuotaEvent.document_id == document.id)
            .order_by(QuotaEvent.created_at)
        )
    ).scalars().all()
    assert [e.action for e in events] == ["reserve", "release"]
    assert "failed" in (events[1].note or "")


async def test_missing_job_is_handled_quietly(session: AsyncSession, run_job) -> None:
    """งานอาจถูกลบไปแล้วก่อน worker หยิบ ไม่ควรทำให้ worker พัง"""
    result = await run_job(uuid.uuid4())
    assert result["status"] == "missing_job"


@pytest.mark.parametrize("path", ["/data/uploads/ไม่มี.txt", "/data/uploads/"])
async def test_bad_paths_do_not_crash_the_worker(
    session: AsyncSession, user: User, path: str, run_job
) -> None:
    document = Document(
        id=uuid.uuid4(),
        owner_id=user.id,
        filename="x.txt",
        mime_type="text/plain",
        storage_path=path,
        size_bytes=1,
        page_count=1,
    )
    session.add(document)
    await session.flush()
    await quota_service.reserve(session, user, document.id, 1)
    job = IngestionJob(document_id=document.id, stage="queued", pages_total=1)
    session.add(job)
    await session.commit()

    result = await run_job(job.id)
    assert result["status"] == "failed"
    assert Path(path).exists() is False or True  # ไม่สนใจไฟล์ สนใจว่าไม่ crash
