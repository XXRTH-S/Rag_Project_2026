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


def _request(forwarded: str | None, peer: str = "172.19.0.5"):
    """จำลองคำขอที่ API ได้รับ *หลัง* ผ่าน proxy มาแล้ว

    ค่าใน forwarded คือสิ่งที่ API เห็นจริง ซึ่งประกอบด้วยส่วนที่ผู้เรียกแต่งมาเอง
    (ซ้ายสุด) ต่อด้วยที่อยู่ที่ proxy แต่ละชั้นเติมให้ตามลำดับ
    """
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 40000)})


def test_client_ip_reads_the_entry_our_own_proxy_wrote(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert ratelimit.client_ip(_request("203.0.113.9")) == "203.0.113.9"

    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    # ngrok เติม 9.9.9.9 (ผู้ใช้จริง) แล้ว Caddy เติม IP ของคอนเทนเนอร์ ngrok ต่อท้าย
    assert ratelimit.client_ip(_request("9.9.9.9, 172.19.0.5")) == "9.9.9.9"


def test_forged_forwarded_for_cannot_move_the_target(monkeypatch) -> None:
    """เทสที่สำคัญที่สุดของไฟล์นี้

    ผู้เรียกเติม entry ได้เฉพาะทาง *ซ้าย* เท่านั้น เพราะ proxy ของเราต่อท้ายเสมอ
    ไม่ว่าจะแต่งมากี่ตัว entry ที่นับจากขวาเข้ามาตามจำนวนชั้นก็ยังเป็นตัวเดิม

    ถ้าเทสนี้แดง แปลว่ามีคนเปลี่ยนไปหยิบตัวซ้ายสุด ซึ่งเท่ากับเปิดให้ใครก็ได้
    เลี่ยง rate limit ทุกชั้นด้วยการใส่ header เองแล้วสุ่มค่าไปเรื่อย ๆ
    """
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    real = ratelimit.client_ip(_request("203.0.113.9"))
    for forgery in ["1.1.1.1", "1.1.1.1, 2.2.2.2", "evil, 8.8.8.8, 4.4.4.4"]:
        spoofed = ratelimit.client_ip(_request(f"{forgery}, 203.0.113.9"))
        assert spoofed == real, f"ปลอมด้วย {forgery!r} แล้วได้ถังใหม่ — เลี่ยงเพดานได้"

    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    real = ratelimit.client_ip(_request("9.9.9.9, 172.19.0.5"))
    for forgery in ["1.1.1.1", "1.1.1.1, 2.2.2.2"]:
        spoofed = ratelimit.client_ip(_request(f"{forgery}, 9.9.9.9, 172.19.0.5"))
        assert spoofed == real, f"ปลอมด้วย {forgery!r} แล้วได้ถังใหม่ — เลี่ยงเพดานได้"


def test_client_ip_ignores_the_header_when_nothing_is_trusted(monkeypatch) -> None:
    """เปิด API ตรงออกอินเทอร์เน็ต = ไม่มี hop ไหนเชื่อได้ ต้องไม่แตะ header เลย"""
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert ratelimit.client_ip(_request("203.0.113.9", peer="10.0.0.3")) == "10.0.0.3"


def test_client_ip_falls_back_when_the_chain_is_shorter_than_configured(monkeypatch) -> None:
    """ตั้งจำนวนชั้นไม่ตรงกับความจริง — ต้องถอยไปใช้ peer ไม่ใช่เดาเอาจากที่มี

    ถอยแบบนี้อาจรวมทุกคนเป็นถังเดียว ซึ่งจำกัดเกินจริง แต่ปลอดภัย
    ดีกว่าหยิบ entry ที่ผู้เรียกแต่งมาแล้วปล่อยให้เลี่ยงเพดานได้
    """
    monkeypatch.setattr(settings, "trusted_proxy_hops", 3)
    assert ratelimit.client_ip(_request("9.9.9.9, 172.19.0.5", peer="10.0.0.3")) == "10.0.0.3"


async def test_different_real_clients_get_different_login_budgets(
    client: AsyncClient, monkeypatch
) -> None:
    """คนละคนผ่าน tunnel เดียวกันต้องมีเพดานของตัวเอง

    นี่คือสิ่งที่พังตอน demo: ngrok ต่อเข้า api ตรง ๆ ทำให้ทุกคำขอมาจาก IP เดียว
    เพดาน 10 ครั้งต่อ 5 นาทีจึงถูกใช้ร่วมกันทั้งงาน คนหนึ่งพิมพ์รหัสผิด
    แล้วล็อกทุกคนออกได้
    """
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    monkeypatch.setattr(settings, "rate_limit_login_attempts", 3)
    monkeypatch.setattr(settings, "rate_limit_login_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_login_attempts_per_email", 0)

    async def attempt(real_ip: str) -> int:
        resp = await client.post(
            "/api/auth/login",
            json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "password": "wrong"},
            headers={"X-Forwarded-For": f"{real_ip}, 172.19.0.5"},
        )
        return resp.status_code

    for _ in range(4):
        await attempt("198.51.100.7")
    assert await attempt("198.51.100.7") == 429, "คนแรกควรเต็มเพดานของตัวเองแล้ว"

    assert await attempt("198.51.100.8") != 429, (
        "คนที่สองโดนบล็อกทั้งที่ยังไม่ได้ลองเลย — เพดานยังยุบเป็นถังเดียวอยู่"
    )


async def test_email_layer_catches_someone_rotating_ips(
    client: AsyncClient, user: User, monkeypatch
) -> None:
    """หมุน IP หนีชั้นแรกได้ แต่ยังชนชั้นอีเมล"""
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    monkeypatch.setattr(settings, "rate_limit_login_attempts", 100)
    monkeypatch.setattr(settings, "rate_limit_login_attempts_per_email", 3)
    monkeypatch.setattr(settings, "rate_limit_login_email_window_seconds", 60)

    codes = []
    for i in range(6):
        resp = await client.post(
            "/api/auth/login",
            json={"email": user.email, "password": f"wrong{i}"},
            headers={"X-Forwarded-For": f"203.0.113.{i}, 172.19.0.5"},
        )
        codes.append(resp.status_code)

    assert 429 in codes, f"หมุน IP แล้วเดารหัสได้ไม่จำกัด — ได้ {codes}"


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
