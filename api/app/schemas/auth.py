import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.base import StrictModel


class LoginRequest(StrictModel):
    email: str  # ไม่ใช้ EmailStr เพื่อเลี่ยง dependency email-validator ที่ต้อง rebuild image
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class QuotaBucket(BaseModel):
    used: int
    limit: int | None
    remaining: int | None


class QuotaOut(BaseModel):
    documents: QuotaBucket
    pages: QuotaBucket
    unlimited: bool
    resets_at: str
    # ส่งเพดานขนาดไฟล์มาด้วย เพื่อให้หน้าเว็บเตือนได้ตั้งแต่ก่อนเริ่มอัป
    # ถ้าให้ฝั่งเว็บตั้งตัวเลขเอง วันที่แก้ MAX_UPLOAD_MB ใน .env ค่าสองฝั่งจะเพี้ยนกัน
    # แล้วผู้ใช้จะเจอ error ที่ไม่ตรงกับที่หน้าจอบอก
    max_upload_bytes: int
