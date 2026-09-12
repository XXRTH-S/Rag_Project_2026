import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsageCounter(Base):
    """ยอดใช้งานรายวันต่อ user — หนึ่งแถวต่อ (user, วัน)

    usage_date เป็นวันที่ตามเวลาไทย ไม่ใช่ UTC ไม่งั้นโควตาจะรีเซ็ตตอน 7 โมงเช้า
    """

    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uq_usage_user_date"),)

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)

    documents_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # หน้าที่จองไว้ตอน upload แต่ยังไม่ commit (job ยังไม่จบ)
    pages_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QuotaEvent(Base):
    """audit trail ของทุกการหัก/คืนโควตา — ไว้ตอบคำถามว่า 'ทำไมโควตาหมด'"""

    __tablename__ = "quota_events"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    # reserve | commit | release
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    delta_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delta_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # clock_timestamp() ไม่ใช่ now() — reserve กับ commit เกิดใน transaction เดียวกันได้
    # ถ้าใช้ now() ทั้งคู่จะได้เวลาเท่ากันแล้วอ่าน audit trail ไม่ออกว่าอะไรเกิดก่อน
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
