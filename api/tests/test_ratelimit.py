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


async def test_two_users_on_the_same_ip_do_not_share_a_budget(
    client: AsyncClient, user: User, admin: User, monkeypatch
) -> None:
    """คนละคนต้องมีเพดานของตัวเอง แม้ออกเน็ตจากที่เดียวกัน

    เดิมนับต่อ IP อย่างเดียว คนทั้งออฟฟิศที่ออกผ่าน NAT ตัวเดียวกันจึงถูกนับรวม
    เป็นคนเดียว คนหนึ่งยิงรัวแล้วทั้งห้องใช้ไม่ได้ ซึ่งไม่ใช่สิ่งที่เพดาน
    "20 ครั้งต่อนาที" ตั้งใจจะสื่อ

    ในเทสทุกคำขอมาจาก IP เดียวกันอยู่แล้ว (ASGI transport) จึงเป็นการจำลอง
    สถานการณ์นั้นพอดี
    """
    monkeypatch.setattr(settings, "rate_limit_chat_per_minute", 2)

    async def login(u: User) -> dict[str, str]:
        resp = await client.post(
            "/api/auth/login", json={"email": u.email, "password": TEST_PASSWORD}
        )
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    first = await login(user)
    second = await login(admin)

    # คนแรกใช้จนเต็มเพดานแล้วโดนบล็อก
    for _ in range(3):
        await client.post("/api/chat", headers=first, json={"message": "สวัสดี"})
    blocked = await client.post("/api/chat", headers=first, json={"message": "สวัสดี"})
    assert blocked.status_code == 429

    # คนที่สองต้องยังใช้ได้ตามปกติ
    resp = await client.post("/api/chat", headers=second, json={"message": "สวัสดี"})
    assert resp.status_code != 429, "คนที่สองโดนบล็อกทั้งที่ยังไม่ได้ใช้โควตาของตัวเองเลย"


async def test_login_is_still_counted_per_ip(client: AsyncClient, user: User, monkeypatch) -> None:
    """login ต้องนับต่อ IP เพราะยังไม่รู้ว่าใครเรียก

    และห้ามไปนับต่ออีเมล ไม่งั้นใครก็ยิงรหัสผิดใส่บัญชีคนอื่นจนเขาเข้าไม่ได้
    ที่นี่พิสูจน์ว่าการลองกับ *คนละอีเมล* จาก IP เดียวกันยังนับรวมกัน
    """
    monkeypatch.setattr(settings, "rate_limit_login_attempts", 3)
    monkeypatch.setattr(settings, "rate_limit_login_window_seconds", 60)

    codes = []
    for i in range(5):
        resp = await client.post(
            "/api/auth/login", json={"email": f"who-{i}@example.com", "password": "wrong"}
        )
        codes.append(resp.status_code)

    assert 429 in codes, f"ยิงหลายอีเมลจาก IP เดียวกันต้องยังโดนนับรวม แต่ได้ {codes}"
