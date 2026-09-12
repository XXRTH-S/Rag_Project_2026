"""สร้างบัญชี admin ตัวแรกจาก .env

ทำตอน startup เพราะระบบไม่มีหน้าสมัครสมาชิกแบบเปิดสาธารณะ — ถ้าไม่มีขั้นนี้
จะไม่มีทางเข้าระบบได้เลยหลัง deploy ใหม่
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.user import User

log = logging.getLogger("app.bootstrap")


async def ensure_admin_user(session: AsyncSession) -> None:
    if not settings.admin_email or not settings.admin_password:
        log.warning("ยังไม่ได้ตั้ง ADMIN_EMAIL/ADMIN_PASSWORD ใน .env — ข้ามการสร้างบัญชี admin")
        return

    email = settings.admin_email.strip().lower()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        session.add(
            User(
                email=email,
                password_hash=hash_password(settings.admin_password),
                role="admin",
                is_active=True,
            )
        )
        await session.commit()
        log.info("สร้างบัญชี admin %s แล้ว", email)
        return

    changed = False
    if user.role != "admin":
        user.role = "admin"
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    # ตามรหัสใน .env เสมอ เพื่อให้กู้บัญชีได้ด้วยการแก้ .env แล้ว restart
    if not verify_password(settings.admin_password, user.password_hash):
        user.password_hash = hash_password(settings.admin_password)
        changed = True

    if changed:
        await session.commit()
        log.info("อัปเดตบัญชี admin %s ให้ตรงกับ .env แล้ว", email)
