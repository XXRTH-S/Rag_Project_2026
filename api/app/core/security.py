from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"


# bcrypt รับได้สูงสุด 72 ไบต์ ไม่ใช่ 72 ตัวอักษร — อักษรไทยกินตัวละ 3 ไบต์
# รหัสผ่านภาษาไทยแค่ 25 ตัวก็เกินแล้ว และ bcrypt โยน ValueError ทิ้งไปดื้อ ๆ
# ถ้าไม่ดักไว้ก่อน ผู้ใช้จะเจอ 500 แทนที่จะเจอข้อความบอกว่ารหัสยาวเกิน
MAX_PASSWORD_BYTES = 72


def password_too_long(plain: str) -> bool:
    return len(plain.encode()) > MAX_PASSWORD_BYTES


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# แฮชของรหัสที่ไม่มีใครใช้ สร้างครั้งเดียวตอน import เพื่อให้ dummy_verify
# เสียเวลาเท่ากับการตรวจรหัสจริง โดยไม่ต้องไปแฮชใหม่ทุกครั้ง
# เขียนเป็น ASCII เพราะต้องไม่เกิน 72 ไบต์ตามข้อจำกัดของ bcrypt ข้างบน
_DUMMY_HASH = hash_password("not-a-real-password-only-for-constant-timing")


def dummy_verify(plain: str) -> None:
    """เผาเวลาเท่ากับการตรวจรหัสผ่านจริง ทั้งที่ไม่มีบัญชีให้ตรวจ

    bcrypt จงใจช้า (หลักสิบถึงร้อยมิลลิวินาที) ถ้าเส้นทาง "ไม่มีอีเมลนี้"
    กลับทันทีโดยไม่แตะ bcrypt เลย ผู้โจมตีจับเวลาคำตอบก็แยกออกทันทีว่า
    อีเมลไหนมีบัญชีอยู่จริง แม้ข้อความ error จะเหมือนกันทุกตัวอักษรก็ตาม
    """
    verify_password(plain, _DUMMY_HASH)


def create_access_token(subject: str, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
