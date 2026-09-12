"""เทสการปิดช่องโจมตีที่ประตูหน้าบ้าน

ก่อนหน้านี้ /api/auth/login ไม่มีเพดานการลองเลย ทั้งที่ระบบมี rate limit
พร้อมใช้อยู่แล้วและเอาไปใช้กับ chat/upload — ประตูที่สำคัญที่สุดกลับไม่มี
"""
import time

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import MAX_PASSWORD_BYTES, dummy_verify, verify_password
from app.models.user import User
from tests.conftest import TEST_PASSWORD


@pytest.fixture
def tight_login_limit(monkeypatch):
    """ลดเพดานให้เทสรันเร็ว — ค่าจริง 10 ครั้งต่อ 5 นาทีทำให้เทสช้าเกินจำเป็น"""
    monkeypatch.setattr(settings, "rate_limit_login_attempts", 3)
    monkeypatch.setattr(settings, "rate_limit_login_window_seconds", 60)


async def test_password_guessing_is_stopped(
    client: AsyncClient, user: User, tight_login_limit
) -> None:
    codes = []
    for i in range(5):
        resp = await client.post(
            "/api/auth/login", json={"email": user.email, "password": f"wrong{i}"}
        )
        codes.append(resp.status_code)

    assert 429 in codes, f"เดารหัสได้ไม่จำกัด — status ที่ได้: {codes}"
    assert codes[:3] == [401, 401, 401], "ครั้งแรก ๆ ต้องยังตอบ 401 ตามปกติ"


async def test_rate_limited_response_says_when_to_retry(
    client: AsyncClient, user: User, tight_login_limit
) -> None:
    """ผู้ใช้ที่พิมพ์ผิดจริง ๆ ต้องรู้ว่าต้องรอนานแค่ไหน ไม่ใช่เจอ 429 เปล่า ๆ"""
    last = None
    for _ in range(5):
        last = await client.post(
            "/api/auth/login", json={"email": user.email, "password": "wrong"}
        )
    assert last is not None
    assert last.status_code == 429
    assert "Retry-After" in last.headers


async def test_correct_password_still_works_within_the_limit(
    client: AsyncClient, user: User, tight_login_limit
) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200


def test_unknown_email_costs_the_same_time_as_a_wrong_password() -> None:
    """กันการไล่เดาว่าอีเมลไหนมีบัญชีอยู่จริงด้วยการจับเวลา

    ถ้าเส้นทาง "ไม่มีอีเมลนี้" กลับทันทีโดยไม่แตะ bcrypt เลย คำตอบจะเร็วกว่า
    กรณีมีบัญชีหลายสิบเท่า ผู้โจมตีแยกออกทันทีแม้ข้อความ error จะเหมือนกันทุกตัวอักษร

    วัดที่ระดับฟังก์ชัน ไม่ใช่ผ่าน HTTP เพราะ latency ของเครือข่ายในเทส
    แกว่งกว่าตัวเลขที่เรากำลังวัด
    """
    from app.core.security import hash_password

    real_hash = hash_password("ของจริง")

    def elapsed(fn) -> float:
        samples = []
        for _ in range(3):
            started = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - started)
        return sorted(samples)[1]  # ค่ากลาง ตัดตัวที่แกว่งออก

    wrong_password = elapsed(lambda: verify_password("ผิด", real_hash))
    no_such_user = elapsed(lambda: dummy_verify("ผิด"))

    # ไม่ต้องเท่ากันเป๊ะ ขอแค่อยู่ในสเกลเดียวกัน (ไม่ใช่ต่างกันสิบเท่า)
    ratio = max(wrong_password, no_such_user) / max(1e-9, min(wrong_password, no_such_user))
    assert ratio < 3, (
        f"เวลาต่างกันมากเกินไป ({wrong_password * 1000:.1f} ms vs {no_such_user * 1000:.1f} ms) "
        "ผู้โจมตีจับเวลาแล้วเดาได้ว่าอีเมลไหนมีบัญชีจริง"
    )


async def test_thai_password_longer_than_bcrypt_limit_is_rejected_cleanly(
    client: AsyncClient, admin: User
) -> None:
    """bcrypt นับ 72 **ไบต์** ไม่ใช่ตัวอักษร — อักษรไทยกินตัวละ 3 ไบต์

    รหัสภาษาไทย 25 ตัวก็เกินแล้ว เดิม bcrypt โยน ValueError ดิบ ๆ กลายเป็น 500
    ทั้งที่ควรบอก admin ว่ารหัสยาวเกินไป
    """
    resp = await client.post(
        "/api/auth/login", json={"email": admin.email, "password": TEST_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    long_thai = "ก" * 40  # 120 ไบต์
    assert len(long_thai.encode()) > MAX_PASSWORD_BYTES

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"email": "long-pw@example.com", "password": long_thai, "role": "user"},
    )
    assert created.status_code == 422, f"ควรได้ 422 ไม่ใช่ {created.status_code}"
    assert "ยาวเกิน" in created.text


async def test_unknown_field_is_rejected_instead_of_ignored(
    client: AsyncClient, admin: User
) -> None:
    """ส่ง is_admin มาแทน role เคยได้บัญชี user ธรรมดาแบบเงียบ ๆ พร้อม 201

    ผู้เรียกไม่มีทางรู้ว่าตัวเองพลาด จนกว่าจะไปเจอว่าบัญชีเข้าหน้า admin ไม่ได้
    """
    resp = await client.post(
        "/api/auth/login", json={"email": admin.email, "password": TEST_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"email": "typo@example.com", "password": "longenough123", "is_admin": True},
    )
    assert created.status_code == 422, f"field ที่ไม่รู้จักต้องถูกปฏิเสธ ไม่ใช่ {created.status_code}"
    assert "is_admin" in created.text
