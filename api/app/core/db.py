from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

# ใช้ NullPool บน serverless เพื่อไม่ให้แต่ละ instance จอง connection ค้างไว้
_pool: dict[str, Any] = (
    {"pool_size": 5, "max_overflow": 5, "pool_pre_ping": True}
    if settings.db_pool_enabled
    else {"poolclass": NullPool}
)

engine = create_async_engine(
    # ใช้ URL ที่แปลงเป็น asyncpg แล้ว
    settings.sqlalchemy_url,
    connect_args=settings.database_connect_args,
    echo=False,
    **_pool,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
