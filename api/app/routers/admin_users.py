"""จัดการผู้ใช้ (admin เท่านั้น)

ทำไมต้องมี: ก่อนหน้านี้ระบบมีแค่บัญชี admin ที่ bootstrap จาก .env
ไม่มีทางสร้างบัญชี role "user" ได้เลย ระบบโควตาทั้งหมด (5 เอกสาร/วัน, 500 หน้า/วัน)
จึงเข้าไม่ถึงในการใช้งานจริง เพราะ admin เป็น unlimited

ไม่มีหน้าสมัครสมาชิกแบบเปิดสาธารณะโดยตั้งใจ — คลังความรู้เป็นเอกสารภายใน
ใครเข้าถึงได้ต้องผ่านการอนุมัติของ admin
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import require_admin
from app.core.security import hash_password
from app.models.user import User
from app.quota import service as quota_service
from app.schemas.auth import UserOut

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])

MIN_PASSWORD_LENGTH = 8


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    role: str = Field(default="user", pattern="^(user|admin)$")


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH, max_length=256)
    role: str | None = Field(default=None, pattern="^(user|admin)$")
    is_active: bool | None = None


class UserWithUsage(UserOut):
    documents_today: int
    pages_today: int
    quota_unlimited: bool


async def _count_admins(session: AsyncSession, *, active_only: bool = True) -> int:
    stmt = select(func.count()).select_from(User).where(User.role == "admin")
    if active_only:
        stmt = stmt.where(User.is_active)
    return (await session.execute(stmt)).scalar_one()


@router.get("", response_model=list[UserWithUsage])
async def list_users(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    users = (await session.execute(select(User).order_by(User.created_at))).scalars().all()

    result = []
    for user in users:
        quota = await quota_service.get_status(session, user)
        result.append(
            UserWithUsage(
                id=user.id,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
                created_at=user.created_at,
                documents_today=quota.documents_used,
                pages_today=quota.pages_used,
                quota_unlimited=quota.unlimited,
            )
        )
    return result


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    email = payload.email.strip().lower()
    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "มีบัญชีอีเมลนี้อยู่แล้ว")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบผู้ใช้")

    # กันไม่ให้ admin ตัดสิทธิ์ตัวเองจนล็อกตัวเองออกจากระบบ
    if user.id == admin.id:
        if payload.role is not None and payload.role != "admin":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ลดสิทธิ์ตัวเองไม่ได้")
        if payload.is_active is False:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ปิดบัญชีตัวเองไม่ได้")

    # กันไม่ให้เหลือระบบที่ไม่มี admin ใช้งานได้เลย
    losing_admin = user.role == "admin" and (
        (payload.role is not None and payload.role != "admin") or payload.is_active is False
    )
    if losing_admin and await _count_admins(session) <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "ต้องมี admin ที่ใช้งานได้อย่างน้อยหนึ่งบัญชี"
        )

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    await session.commit()
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """ลบผู้ใช้ — เอกสารและ chunk ของเขาหายตามด้วย (ON DELETE CASCADE)

    ประวัติแชทไม่หายเพราะ chat_sessions.user_id เป็น ON DELETE SET NULL
    สถิติย้อนหลังจึงยังอ่านได้
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบผู้ใช้")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ลบบัญชีตัวเองไม่ได้")
    if user.role == "admin" and await _count_admins(session) <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "ต้องมี admin ที่ใช้งานได้อย่างน้อยหนึ่งบัญชี"
        )

    await session.delete(user)
    await session.commit()
