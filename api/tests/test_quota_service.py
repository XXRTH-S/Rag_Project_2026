import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.models.quota import QuotaEvent, UsageCounter
from app.models.user import User
from app.quota import service


async def _new_document(session: AsyncSession, user: User, pages: int) -> uuid.UUID:
    """quota_events.document_id มี FK ไป documents — แถวเอกสารต้องมาก่อนเสมอ

    ตรงกับ flow จริง: สร้าง document แล้ว reserve ใน transaction เดียวกัน
    """
    doc = Document(
        id=uuid.uuid4(),
        owner_id=user.id,
        filename=f"{uuid.uuid4().hex[:8]}.pdf",
        mime_type="application/pdf",
        storage_path=f"/data/uploads/{uuid.uuid4().hex}.pdf",
        size_bytes=1024,
        page_count=pages,
    )
    session.add(doc)
    await session.flush()
    return doc.id


async def _reserve(session: AsyncSession, user: User, pages: int) -> uuid.UUID:
    doc_id = await _new_document(session, user, pages)
    await service.reserve(session, user, doc_id, pages)
    await session.commit()
    return doc_id


async def test_fresh_user_has_full_quota(session: AsyncSession, user: User) -> None:
    status = await service.get_status(session, user)
    assert status.documents_used == 0
    assert status.documents_remaining == settings.user_daily_document_limit
    assert status.pages_remaining == settings.user_daily_page_limit
    assert status.unlimited is False


async def test_reserve_decrements_remaining(session: AsyncSession, user: User) -> None:
    await _reserve(session, user, 20)
    status = await service.get_status(session, user)
    assert status.documents_used == 1
    assert status.pages_used == 20
    assert status.pages_remaining == settings.user_daily_page_limit - 20


async def test_document_limit_blocks_sixth_upload(session: AsyncSession, user: User) -> None:
    for _ in range(settings.user_daily_document_limit):
        await _reserve(session, user, 1)

    doc_id = await _new_document(session, user, 1)
    with pytest.raises(service.QuotaExceeded) as exc:
        await service.reserve(session, user, doc_id, 1)

    assert "5 เอกสาร" in exc.value.reason
    assert exc.value.status.documents_remaining == 0


async def test_page_limit_blocks_oversized_batch(session: AsyncSession, user: User) -> None:
    # 400 หน้าต้องแบ่งเป็นสองเอกสาร เพราะเพดานต่อเอกสารคือ 200
    await _reserve(session, user, 200)
    await _reserve(session, user, 200)

    doc_id = await _new_document(session, user, 150)
    with pytest.raises(service.QuotaExceeded) as exc:
        await service.reserve(session, user, doc_id, 150)

    assert exc.value.status.pages_remaining == 100


async def test_per_document_cap_blocks_single_huge_file(
    session: AsyncSession, user: User
) -> None:
    # ยังไม่ถึงโควตารายวัน แต่ไฟล์เดียวใหญ่เกินเพดานต่อเอกสาร
    too_big = settings.user_max_pages_per_document + 1
    doc_id = await _new_document(session, user, too_big)
    with pytest.raises(service.QuotaExceeded) as exc:
        await service.reserve(session, user, doc_id, too_big)

    assert "ต่อเอกสาร" in exc.value.reason


async def test_admin_is_never_blocked(session: AsyncSession, admin: User) -> None:
    for _ in range(settings.user_daily_document_limit + 3):
        await _reserve(session, admin, settings.user_daily_page_limit)

    status = await service.get_status(session, admin)
    assert status.unlimited is True
    assert status.documents_limit is None
    assert status.pages_remaining is None
    # ยังนับอยู่ เพื่อให้ analytics ตอบได้ว่าใครใช้ทรัพยากรไปเท่าไหร่
    assert status.documents_used == settings.user_daily_document_limit + 3


async def test_commit_replaces_estimate_with_actual_pages(
    session: AsyncSession, user: User
) -> None:
    # docx ประเมินไว้ 10 หน้า แต่ parse จริงได้ 4 หน้า
    doc_id = await _reserve(session, user, 10)
    await service.commit(session, user, doc_id, actual_pages=4)
    await session.commit()

    status = await service.get_status(session, user)
    assert status.pages_used == 4

    counter = (
        await session.execute(select(UsageCounter).where(UsageCounter.user_id == user.id))
    ).scalar_one()
    assert counter.pages_reserved == 0
    assert counter.pages_used == 4


async def test_release_refunds_document_and_pages(session: AsyncSession, user: User) -> None:
    doc_id = await _reserve(session, user, 50)
    await service.release(session, user, doc_id, note="job failed before OCR")
    await session.commit()

    status = await service.get_status(session, user)
    assert status.documents_used == 0
    assert status.pages_used == 0


async def test_release_can_keep_the_document_charge(session: AsyncSession, user: User) -> None:
    # ใช้ตอนไฟล์ผ่าน OCR ไปบางส่วนแล้ว — คืนหน้าที่เหลือได้ แต่ไม่คืนสิทธิ์เอกสาร
    doc_id = await _reserve(session, user, 50)
    await service.release(session, user, doc_id, note="partial", refund_document=False)
    await session.commit()

    status = await service.get_status(session, user)
    assert status.documents_used == 1
    assert status.pages_used == 0


async def test_every_change_leaves_an_audit_row(session: AsyncSession, user: User) -> None:
    doc_id = await _reserve(session, user, 7)
    await service.commit(session, user, doc_id, actual_pages=7)
    await session.commit()

    events = (
        await session.execute(
            select(QuotaEvent).where(QuotaEvent.user_id == user.id).order_by(QuotaEvent.created_at)
        )
    ).scalars().all()
    assert [e.action for e in events] == ["reserve", "commit"]


async def test_concurrent_reserves_cannot_oversell(
    session: AsyncSession, make_session, user: User
) -> None:
    """สองคำขอพร้อมกันที่รวมกันเกินโควตาที่เหลือ ต้องผ่านได้แค่หนึ่ง

    นี่คือเหตุผลที่ _lock_counter ใช้ SELECT ... FOR UPDATE — ถ้าอ่านยอดโดยไม่ล็อก
    ทั้งคู่จะเห็นยอดเดิมแล้วจองผ่านทั้งสอง กลายเป็นใช้เกินโควตา
    """
    limit = settings.user_daily_page_limit
    # ขนาดต่อไฟล์ต้องไม่เกินเพดานต่อเอกสาร ไม่งั้นจะถูกปฏิเสธด้วยเหตุผลคนละเรื่อง
    # แล้วเทสจะผ่านโดยไม่ได้พิสูจน์เรื่อง race เลย
    chunk = min(150, settings.user_max_pages_per_document)

    # เติมให้เหลือโควตาพอสำหรับคำขอเดียวเท่านั้น
    prefill = limit - chunk - (chunk // 2)
    while prefill > 0:
        take = min(chunk, prefill)
        await _reserve(session, user, take)
        prefill -= take

    before = await service.get_status(session, user)
    assert before.pages_remaining < 2 * chunk, "ต้องเหลือโควตาพอสำหรับคำขอเดียวเท่านั้น"

    async def attempt() -> bool:
        s = make_session()
        try:
            doc_id = await _new_document(s, user, chunk)
            await service.reserve(s, user, doc_id, chunk)
            await s.commit()
            return True
        except service.QuotaExceeded:
            await s.rollback()
            return False

    results = await asyncio.gather(attempt(), attempt())

    assert sum(results) == 1, f"ควรผ่านแค่หนึ่ง แต่ได้ {results}"

    verify = make_session()
    after = await service.get_status(verify, user)
    assert after.pages_used == before.pages_used + chunk
    assert after.pages_used <= limit
