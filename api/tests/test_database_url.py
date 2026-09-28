"""DATABASE_URL ที่ผู้ให้บริการ managed ให้มา ต้องใช้ได้โดยไม่ต้องแก้ด้วยมือ

Neon, Supabase, Railway คืน connection string ขึ้นต้นด้วย `postgresql://`
ซึ่ง SQLAlchemy แปลว่า "ใช้ psycopg2" — โปรเจกต์นี้ใช้ asyncpg และไม่ได้ติดตั้ง
psycopg2 ผลคือ create_async_engine ล้มตั้งแต่ตอน import ด้วย ModuleNotFoundError

บน serverless เรื่องนี้โผล่ออกมาเป็นแค่ FUNCTION_INVOCATION_FAILED ซึ่งไม่บอกอะไรเลย
(เจอจริงตอนขึ้น Vercel ครั้งแรก 22 ก.ย. 2026) การวาง URL ที่เขาให้มาตรง ๆ
คือสิ่งที่ทุกคนทำ จึงต้องรองรับ ไม่ใช่ให้คนจำว่าต้องเติม +asyncpg เอง
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings


def _settings(url: str) -> Settings:
    return Settings(_env_file=None, database_url=url)


@pytest.mark.parametrize(
    "given",
    [
        "postgresql://u:p@ep-x.aws.neon.tech/neondb",
        "postgres://u:p@db.abc.supabase.co:5432/postgres",
        "postgresql+asyncpg://rag:changeme@postgres:5432/rag",
    ],
)
def test_every_shape_ends_up_on_asyncpg(given: str) -> None:
    assert _settings(given).sqlalchemy_url.startswith("postgresql+asyncpg://")


def test_the_url_we_already_use_is_left_alone() -> None:
    """ของเดิมต้องไม่เปลี่ยน ไม่งั้นการแก้นี้จะไปพังเครื่องที่ใช้งานได้อยู่แล้ว"""
    url = "postgresql+asyncpg://rag:changeme@postgres:5432/rag"
    settings = _settings(url)

    assert settings.sqlalchemy_url == url
    assert settings.database_connect_args == {}


def test_libpq_only_params_move_out_of_the_url() -> None:
    """asyncpg ไม่รู้จัก sslmode/channel_binding — ปล่อยไว้แล้วจะ TypeError ตอนต่อ"""
    settings = _settings(
        "postgresql://u:p@ep-x.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    )

    assert settings.sqlalchemy_url == "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/neondb"
    assert settings.database_connect_args == {"ssl": "require"}


def test_other_query_params_are_kept() -> None:
    """ตัดเฉพาะของ libpq · พารามิเตอร์อื่นอาจมีความหมายกับ asyncpg"""
    settings = _settings("postgresql://u:p@h/db?sslmode=require&prepared_statement_cache_size=0")

    assert "prepared_statement_cache_size=0" in settings.sqlalchemy_url
    assert "sslmode" not in settings.sqlalchemy_url


def test_sslmode_disable_needs_no_connect_arg() -> None:
    assert _settings("postgresql://u:p@h/db?sslmode=disable").database_connect_args == {}


@pytest.mark.parametrize(
    "given",
    [
        "postgresql://u:p@ep-x.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
        "postgres://u:p@db.abc.supabase.co:5432/postgres",
    ],
)
def test_sqlalchemy_accepts_the_result(given: str) -> None:
    """เทสที่สำคัญที่สุด — พิสูจน์ว่า create_async_engine ไม่ล้มตอน import

    ไม่ได้ต่อจริง แค่สร้าง engine ซึ่งเป็นจุดที่ SQLAlchemy เลือก driver
    และเป็นจุดเดียวกับที่เคยพังบน Vercel
    """
    settings = _settings(given)

    engine = create_async_engine(
        settings.sqlalchemy_url, connect_args=settings.database_connect_args
    )

    assert engine.dialect.driver == "asyncpg"


def test_pooling_is_on_by_default() -> None:
    """เครื่องที่รันเป็นโปรเซสยาว ๆ ต้องได้ pool ตามเดิม"""
    assert Settings(_env_file=None).db_pool_enabled is True
