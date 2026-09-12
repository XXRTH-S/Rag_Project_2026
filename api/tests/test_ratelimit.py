"""เทส rate limit กับ Redis จริง

ไม่ mock เพราะสิ่งที่ต้องพิสูจน์คือ INCR/EXPIRE ทำงานถูกและ key หมดอายุจริง
"""
import uuid

import pytest
from httpx import AsyncClient

from app.core import ratelimit
from app.core.config import settings
from app.models.user import User
from tests.conftest import TEST_PASSWORD


@pytest.fixture
def scope() -> str:
    # key ไม่ซ้ำกันต่อเทส ไม่งั้นตัวนับค้างข้ามเทส
    return f"test-{uuid.uuid4().hex[:8]}"


async def test_allows_up_to_the_limit(scope: str) -> None:
    for i in range(3):
        verdict = await ratelimit.hit(scope, limit=3, window_seconds=60)
        assert verdict.allowed, f"ครั้งที่ {i + 1} ควรผ่าน"
    assert verdict.remaining == 0


async def test_blocks_beyond_the_limit(scope: str) -> None:
    for _ in range(3):
        await ratelimit.hit(scope, limit=3, window_seconds=60)

    verdict = await ratelimit.hit(scope, limit=3, window_seconds=60)
    assert verdict.allowed is False
    assert verdict.retry_after > 0
    assert verdict.retry_after <= 60


async def test_counters_are_isolated_per_key(scope: str) -> None:
    await ratelimit.hit(scope, limit=1, window_seconds=60)
    other = await ratelimit.hit(f"{scope}-other", limit=1, window_seconds=60)
    assert other.allowed


async def test_limit_zero_disables_the_check(scope: str) -> None:
    """ตั้ง limit เป็น 0 หรือติดลบ = ปิดการจำกัด ไม่ใช่บล็อกทุกคำขอ"""
    for _ in range(5):
        assert (await ratelimit.hit(scope, limit=0, window_seconds=60)).allowed


async def test_chat_endpoint_returns_429_with_retry_after(
    client: AsyncClient, user: User, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_chat_per_minute", 2)

    login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    statuses = []
    for _ in range(4):
        resp = await client.post("/api/chat", headers=headers, json={"message": "สวัสดี"})
        statuses.append(resp.status_code)

    assert 429 in statuses, f"ควรโดนจำกัดบ้าง แต่ได้ {statuses}"
    blocked = next(s for s in statuses if s == 429)
    assert blocked == 429

    resp = await client.post("/api/chat", headers=headers, json={"message": "สวัสดี"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0
