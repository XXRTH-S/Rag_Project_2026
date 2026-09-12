import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# ต้องตรงกับ EMBEDDING_DIM ของ bge-m3 และตรงกับ migration
# เปลี่ยนค่านี้ = ต้องเขียน migration ใหม่ ไม่ใช่แก้ config อย่างเดียว
EMBEDDING_DIM = 1024


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # pending | processing | ready | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    collection: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)

    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True เมื่อเป็นไฟล์ที่ไม่มีหน่วยหน้า (docx/txt/html) แล้วเราประเมินจากจำนวนตัวอักษร
    page_count_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # จำนวนหน้าที่ต้องผ่าน OCR จริง (หน้าที่มี text layer อยู่แล้วไม่นับ)
    ocr_page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # queued | detect | ocr | parse | chunk | embed | done | failed
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    queue: Mapped[str] = mapped_column(String(32), nullable=False, default="ocr_user")
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # เก็บไว้ตั้งแต่แรกเพราะเป็นข้อมูลที่ใช้ตัดสินว่าเมื่อไหร่ต้องขยายฮาร์ดแวร์
    gpu_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # snapshot ของ `ollama ps` ตอน job เริ่ม — จับกรณีโมเดลล้นไปรันบน CPU แบบเงียบ ๆ
    processor_note: Mapped[str | None] = mapped_column(String(64), nullable=True)

    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # denormalize ไว้เพื่อ filter สิทธิ์ที่ระดับ SQL ได้โดยไม่ต้อง join
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # จาก OCR หรือ parse ตรง — ใช้ debug คุณภาพ retrieval
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="parse")

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # ข้อความที่ตัดคำด้วย pythainlp แล้ว คั่นด้วยช่องว่าง — Postgres ตัดคำไทยเองไม่ได้
    # คอลัมน์ search_vector ใน DB เป็น generated column จากคอลัมน์นี้ จึงไม่ต้อง map มา
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
