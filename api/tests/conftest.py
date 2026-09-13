"""เทสโควตาต้องยิงใส่ PostgreSQL จริง

เพราะสิ่งที่ต้องพิสูจน์คือ `SELECT ... FOR UPDATE` กับ `ON CONFLICT DO NOTHING`
ทำงานถูกจริงตอนมีคำขอพร้อมกัน ซึ่ง mock ไม่ได้บอกอะไรเลย

conftest นี้สร้าง database แยก (<db>_test) แล้วรัน alembic ของจริงลงไป
ไม่ใช้ Base.metadata.create_all เพราะ migration มี extension, HNSW index
และ CHECK constraint ที่ create_all สร้างไม่ได้
"""
import asyncio
import os
import subprocess
import uuid
from collections.abc import AsyncGenerator
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User

# ต้องครบทุกตาราง — ตารางที่ไม่ได้ผูก CASCADE กับ users (เช่น prompt_configs และ
# chat_sessions ที่ user_id เป็น ON DELETE SET NULL) จะตกค้างข้ามเทสถ้าไม่ล้างเอง
# แล้วเทสตัวหลังจะเห็นข้อมูลของตัวก่อนหน้า ซึ่งกลบปัญหาจริงได้
TABLES_TO_CLEAR = (
    "users, usage_counters, quota_events, documents, ingestion_jobs, chunks, "
    "prompt_configs, chat_sessions, chat_messages, message_citations, feedback"
)


def _test_database_url() -> str:
    parts = urlsplit(settings.database_url)
    return urlunsplit(parts._replace(path=parts.path.rstrip("/") + "_test"))


def _asyncpg_dsn(url: str, database: str | None = None) -> str:
    """asyncpg.connect ไม่รู้จัก scheme แบบ postgresql+asyncpg://"""
    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://"))
    if database is not None:
        parts = parts._replace(path=f"/{database}")
    return urlunsplit(parts)


async def _recreate_database() -> None:
    admin_dsn = _asyncpg_dsn(settings.database_url, database="postgres")
    name = urlsplit(_test_database_url()).path.lstrip("/")
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> None:
    """สร้าง test database ครั้งเดียวต่อ session แล้วรัน migration ของจริง"""
    asyncio.run(_recreate_database())

    env = {**os.environ, "DATABASE_URL": _test_database_url()}
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        # อ่าน returncode เองเพื่อแนบ stdout/stderr ของ alembic ไปกับ error
        # ไม่งั้นเทสล้มโดยบอกแค่ "คำสั่งคืนค่า 1" ซึ่งตามต่อไม่ได้เลย
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade ล้มเหลว:\n{result.stdout}\n{result.stderr}")


@pytest_asyncio.fixture
async def engine(migrated_test_database) -> AsyncGenerator:
    eng = create_async_engine(_test_database_url(), poolclass=None)
    async with eng.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES_TO_CLEAR} RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_rate_limits() -> AsyncGenerator[None, None]:
    """ล้างตัวนับ rate limit ก่อนทุกเทส

    ตัวนับอยู่ใน Redis จึงค้างข้ามเทส ถ้าไม่ล้าง เทสที่อัปโหลดหลายไฟล์รวมกัน
    จะไปชนเพดานรายชั่วโมงแล้วล้มด้วย 429 ทั้งที่ไม่เกี่ยวกับสิ่งที่กำลังทดสอบ
    """
    from app.core import ratelimit

    client = ratelimit._redis()
    keys = [key async for key in client.scan_iter("rl:*")]
    if keys:
        await client.delete(*keys)
    yield
    await ratelimit.close()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


@pytest_asyncio.fixture
async def make_session(engine):
    """สร้าง session อิสระเพิ่ม สำหรับเทสที่ต้องมีสอง transaction พร้อมกัน"""
    created: list[AsyncSession] = []

    def factory() -> AsyncSession:
        s = AsyncSession(engine, expire_on_commit=False)
        created.append(s)
        return s

    yield factory
    for s in created:
        await s.close()


TEST_PASSWORD = "correct-horse-battery"


async def _make_user(session: AsyncSession, role: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{role}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(TEST_PASSWORD),
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


@pytest_asyncio.fixture
async def user(session: AsyncSession) -> User:
    return await _make_user(session, "user")


@pytest_asyncio.fixture
async def admin(session: AsyncSession) -> User:
    return await _make_user(session, "admin")


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncGenerator:
    """ยิง HTTP ใส่ app จริงผ่าน ASGI โดยไม่ต้องเปิดพอร์ต

    ไม่รัน lifespan ตั้งใจ — ไม่งั้น ensure_admin_user จะไปเขียน database ตัวจริง
    """
    from httpx import ASGITransport, AsyncClient

    from app.core.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
