import uuid
from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
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
