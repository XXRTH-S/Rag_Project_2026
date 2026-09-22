import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import decode_access_token
from app.models.user import User

COOKIE_NAME = "access_token"

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="ต้องเข้าสู่ระบบก่อน",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(request: Request) -> str | None:
    """รับได้ทั้ง cookie (หน้าเว็บ) และ Authorization header (สคริปต์/เทส)"""
    header = request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(COOKIE_NAME)


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    token = _extract_token(request)
    if not token:
        raise _UNAUTHORIZED

    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise _UNAUTHORIZED from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


async def get_optional_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """คืนผู้ใช้ถ้าล็อกอินอยู่ ไม่งั้นคืน None โดยไม่โยน 401

    ใช้กับ endpoint ที่ต้องตอบทุกคนได้ แต่ตอบ *ไม่เท่ากัน* ตามสิทธิ์
    เช่น /health/deep ที่ monitor ภายนอกต้องเรียกได้โดยไม่มี credential
    แต่รายละเอียดอย่างชื่อโมเดลและรุ่นซอฟต์แวร์ควรเห็นเฉพาะ admin
    """
    token = _extract_token(request)
    if not token:
        return None

    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None

    user = await session.get(User, user_id)
    return user if user is not None and user.is_active else None


async def require_ingestion() -> None:
    """ปิดเส้นทางนำเข้าเอกสารเมื่อรันในที่ที่ทำไม่ได้จริง

    OCR ใช้เวลาเป็นนาทีและต้องใช้ GPU · การตัดคำกับการอ่าน PDF ต้องใช้
    poppler กับ libmagic ซึ่งเป็น system binary · ไฟล์ต้นฉบับต้องอยู่บนดิสก์
    ที่ไม่หายไป — serverless ไม่มีสักอย่าง

    ตอบ 503 พร้อมบอกว่าต้องไปทำที่ไหน ดีกว่าปล่อยให้ล้มด้วย ImportError
    หรือรับไฟล์ไว้แล้วมันหายตอน container ถูกรีไซเคิล
    """
    if not settings.ingestion_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "ระบบนี้เปิดเฉพาะการค้นหาและถาม-ตอบ "
                "การนำเข้าเอกสารต้องทำผ่านเครื่องที่มี worker และ GPU"
            ),
        )


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="ต้องเป็น admin เท่านั้น"
        )
    return user
