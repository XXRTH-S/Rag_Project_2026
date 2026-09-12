from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_user
from app.models.user import User
from app.quota import service
from app.schemas.auth import QuotaOut

router = APIRouter(prefix="/api/me", tags=["quota"])


@router.get("/quota", response_model=QuotaOut)
async def my_quota(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """หน้า UI ต้องเรียกอันนี้ก่อน user เลือกไฟล์ ไม่ใช่ไปเด้ง 429 ทีหลัง"""
    status = await service.get_status(session, user)
    return status.to_dict()
