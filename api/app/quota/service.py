"""โควตารายวัน: reserve → commit → release

กติกา (PLAN.md ข้อ 8): user = 5 เอกสาร/วัน **และ** 500 หน้า/วัน · admin = ไม่จำกัด

ทำไมต้อง reserve ก่อนเข้าคิว: บนการ์ด 6GB OCR ใช้ ~25 วินาที/หน้า ถ้ารอหักโควตา
ตอนงานเสร็จ user จะเผา GPU ไปเป็นชั่วโมงก่อนได้รู้ว่าเกินโควตา

admin ถูกนับด้วยแต่ไม่ถูกบล็อก — หน้า analytics ต้องตอบได้ว่าใครใช้ทรัพยากรไปเท่าไหร่
"""
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.quota import QuotaEvent, UsageCounter
from app.models.user import User


@dataclass
class QuotaStatus:
    documents_used: int
    pages_used: int
    documents_limit: int | None  # None = ไม่จำกัด
    pages_limit: int | None
    resets_at: datetime
    unlimited: bool

    @property
    def documents_remaining(self) -> int | None:
        if self.documents_limit is None:
            return None
        return max(0, self.documents_limit - self.documents_used)

    @property
    def pages_remaining(self) -> int | None:
        if self.pages_limit is None:
            return None
        return max(0, self.pages_limit - self.pages_used)

    def to_dict(self) -> dict:
        return {
            "documents": {
                "used": self.documents_used,
                "limit": self.documents_limit,
                "remaining": self.documents_remaining,
            },
            "pages": {
                "used": self.pages_used,
                "limit": self.pages_limit,
                "remaining": self.pages_remaining,
            },
            "unlimited": self.unlimited,
            "resets_at": self.resets_at.isoformat(),
        }


class QuotaExceeded(Exception):
    """ยิงกลับเป็น HTTP 429 พร้อมยอดคงเหลือและเวลารีเซ็ต"""

    def __init__(self, reason: str, status: QuotaStatus, requested_pages: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.requested_pages = requested_pages

    def to_dict(self) -> dict:
        return {"error": "quota_exceeded", "reason": self.reason, **self.status.to_dict()}


def _is_unlimited(user: User) -> bool:
    return user.is_admin and settings.admin_unlimited


async def _lock_counter(session: AsyncSession, user_id: uuid.UUID) -> UsageCounter:
    """ได้แถวของวันนี้แบบล็อกไว้แล้ว — กัน race ตอน user อัปหลายไฟล์พร้อมกัน

    ON CONFLICT DO NOTHING ทำให้สองคำขอที่เข้ามาพร้อมกันไม่ชนกันที่ unique constraint
    แล้วค่อย SELECT ... FOR UPDATE เพื่อ serialize การอ่าน-เขียนยอด
    """
    today = settings.today()

    await session.execute(
        text(
            """
            INSERT INTO usage_counters (id, user_id, usage_date)
            VALUES (:id, :user_id, :usage_date)
            ON CONFLICT (user_id, usage_date) DO NOTHING
            """
        ),
        {"id": uuid.uuid4(), "user_id": user_id, "usage_date": today},
    )

    result = await session.execute(
        select(UsageCounter)
        .where(UsageCounter.user_id == user_id, UsageCounter.usage_date == today)
        .with_for_update()
    )
    return result.scalar_one()


def _status_from(counter: UsageCounter, unlimited: bool) -> QuotaStatus:
    return QuotaStatus(
        documents_used=counter.documents_used,
        # หน้าที่จองไว้แต่ยังไม่เสร็จก็ถือว่าใช้ไปแล้วในสายตาของ user
        pages_used=counter.pages_used + counter.pages_reserved,
        documents_limit=None if unlimited else settings.user_daily_document_limit,
        pages_limit=None if unlimited else settings.user_daily_page_limit,
        resets_at=settings.next_quota_reset(),
        unlimited=unlimited,
    )


async def get_status(session: AsyncSession, user: User) -> QuotaStatus:
    today = settings.today()
    result = await session.execute(
        select(UsageCounter).where(
            UsageCounter.user_id == user.id, UsageCounter.usage_date == today
        )
    )
    counter = result.scalar_one_or_none()
    if counter is None:
        # default=0 ของ mapped_column ทำงานตอน INSERT ไม่ใช่ตอนสร้าง object
        # ถ้าไม่ใส่ค่าเอง ทุกช่องจะเป็น None แล้ว user ที่ยังไม่เคยอัปโหลดจะทำให้พัง
        counter = UsageCounter(
            user_id=user.id,
            usage_date=today,
            documents_used=0,
            pages_used=0,
            pages_reserved=0,
        )
    return _status_from(counter, _is_unlimited(user))


async def reserve(
    session: AsyncSession,
    user: User,
    document_id: uuid.UUID,
    pages: int,
) -> QuotaStatus:
    """จองโควตาก่อนเข้าคิว — ต้องเรียกใน transaction เดียวกับที่สร้าง document"""
    if pages < 1:
        raise ValueError("pages ต้องอย่างน้อย 1")

    unlimited = _is_unlimited(user)
    counter = await _lock_counter(session, user.id)
    status = _status_from(counter, unlimited)

    if not unlimited:
        if pages > settings.user_max_pages_per_document:
            # ไม่มีข้อนี้ ไฟล์ 500 หน้าไฟล์เดียวยึดคิว GPU ได้ทั้งวัน (บน 3050 = 4 ชั่วโมง)
            raise QuotaExceeded(
                f"เอกสารนี้มี {pages} หน้า เกินเพดาน "
                f"{settings.user_max_pages_per_document} หน้าต่อเอกสาร",
                status,
                pages,
            )
        if status.documents_used >= settings.user_daily_document_limit:
            raise QuotaExceeded(
                f"วันนี้อัปโหลดครบ {settings.user_daily_document_limit} เอกสารแล้ว", status, pages
            )
        if status.pages_used + pages > settings.user_daily_page_limit:
            raise QuotaExceeded(
                f"เหลือโควตา {status.pages_remaining} หน้า แต่เอกสารนี้มี {pages} หน้า",
                status,
                pages,
            )

    counter.documents_used += 1
    counter.pages_reserved += pages
    session.add(
        QuotaEvent(
            user_id=user.id,
            document_id=document_id,
            action="reserve",
            delta_documents=1,
            delta_pages=pages,
        )
    )
    await session.flush()
    return _status_from(counter, unlimited)


async def _reserved_pages_for(session: AsyncSession, document_id: uuid.UUID) -> int:
    """หน้าที่จองไว้จริงของเอกสารนี้ — อ่านจาก audit trail ไม่ต้องให้ caller จำเอง"""
    result = await session.execute(
        select(QuotaEvent.delta_pages).where(
            QuotaEvent.document_id == document_id, QuotaEvent.action == "reserve"
        )
    )
    return sum(result.scalars().all())


async def commit(
    session: AsyncSession,
    user: User,
    document_id: uuid.UUID,
    actual_pages: int,
) -> QuotaStatus:
    """ย้ายจาก reserved มาเป็น used ด้วยจำนวนหน้าจริง

    จำเป็นเพราะ docx/txt/html ไม่มีหน่วยหน้า เราประเมินจากจำนวนตัวอักษรตอน reserve
    แล้วมารู้ค่าจริงหลัง parse เสร็จ
    """
    reserved = await _reserved_pages_for(session, document_id)
    counter = await _lock_counter(session, user.id)

    counter.pages_reserved = max(0, counter.pages_reserved - reserved)
    counter.pages_used += actual_pages
    session.add(
        QuotaEvent(
            user_id=user.id,
            document_id=document_id,
            action="commit",
            delta_documents=0,
            delta_pages=actual_pages,
            note=f"reserved={reserved}",
        )
    )
    await session.flush()
    return _status_from(counter, _is_unlimited(user))


async def release(
    session: AsyncSession,
    user: User,
    document_id: uuid.UUID,
    *,
    note: str,
    refund_document: bool = True,
) -> QuotaStatus:
    """คืนโควตาเมื่อ job ล้มก่อนแตะ GPU

    **ห้ามเรียกหลังไฟล์ผ่าน OCR ไปแล้ว** — ทรัพยากรถูกใช้ไปจริง
    ถ้าคืนให้ user จะอัป-ลบ-อัปวนไม่จบและยึดคิว GPU ได้ไม่จำกัด
    """
    reserved = await _reserved_pages_for(session, document_id)
    counter = await _lock_counter(session, user.id)

    counter.pages_reserved = max(0, counter.pages_reserved - reserved)
    if refund_document:
        counter.documents_used = max(0, counter.documents_used - 1)

    session.add(
        QuotaEvent(
            user_id=user.id,
            document_id=document_id,
            action="release",
            delta_documents=-1 if refund_document else 0,
            delta_pages=-reserved,
            note=note[:255],
        )
    )
    await session.flush()
    return _status_from(counter, _is_unlimited(user))
