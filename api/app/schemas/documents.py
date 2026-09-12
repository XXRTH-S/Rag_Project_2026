import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    status: str
    collection: str
    page_count: int
    page_count_estimated: bool
    ocr_page_count: int
    size_bytes: int
    created_at: datetime

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    stage: str
    progress: int
    pages_done: int
    pages_total: int
    queue: str
    error: str | None
    processor_note: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class UploadAccepted(BaseModel):
    document: DocumentOut
    job: JobOut
    # ให้ UI บอก user ได้ว่าต้องรอนานแค่ไหน — บนการ์ดนี้เป็นหลักสิบนาทีถึงหลายชั่วโมง
    estimated_seconds: float
    ocr_pages: int
