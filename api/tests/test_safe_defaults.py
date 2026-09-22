"""ค่าเริ่มต้นต้องพังไปทางปลอดภัย และเทสต้องไม่ขึ้นกับ config ของ deployment

สองเรื่องในไฟล์เดียวกันเพราะเป็นบทเรียนเดียวกัน — ทั้งคู่เกิดจากการที่ค่า runtime
เล็ดลอดไปอยู่ในที่ที่ไม่ควรมีผล

1. API_DOCS_ENABLED เคย default เป็น true แล้วหวังให้คนจำได้ว่าต้องปิดตอนขึ้นใช้จริง
   ซึ่งลืมจริงตอนเปิด tunnel ให้คนนอกเข้ามาดู (21 ก.ย. 2026)

2. COOKIE_SECURE=true จาก docker-compose.https.yml เล็ดลอดเข้าคอนเทนเนอร์ที่ pytest
   รันอยู่ ทำให้ cookie เป็น Secure แล้ว client ไม่ส่งกลับผ่าน http — เทสที่พึ่ง cookie
   แดงทั้งชุดทั้งที่โค้ดไม่ผิด ซึ่งกลบบั๊กจริงที่อาจเกิดพร้อมกันได้
"""
import pytest
from httpx import AsyncClient

from app.core.config import Settings, settings
from app.models.user import User
from tests.conftest import TEST_PASSWORD


def test_api_docs_are_closed_when_nobody_sets_them(monkeypatch) -> None:
    """ไม่ตั้งอะไรเลย = ปิด · การเปิดต้องเป็นการตัดสินใจที่เขียนไว้ชัด ๆ เสมอ"""
    monkeypatch.delenv("API_DOCS_ENABLED", raising=False)

    # _env_file=None เพื่อวัด "ค่าที่โค้ดแจกให้" ล้วน ๆ ไม่ปนกับไฟล์ .env ของเครื่องไหน
    fresh = Settings(_env_file=None)

    assert fresh.api_docs_enabled is False, (
        "default ของ API_DOCS_ENABLED ต้องเป็น false — "
        "ค่าเริ่มต้นที่เปิดผัง API ให้คนนอกคือค่าที่ลืมปิดแล้วไม่มีใครรู้"
    )


def test_app_wiring_follows_the_setting() -> None:
    """กันการลบเงื่อนไขใน main.py ทิ้งแล้วเปิด /docs ค้างไว้โดยไม่มีใครสังเกต

    เทียบกับค่า setting ที่คอนเทนเนอร์นี้เห็นจริง จึงผ่านได้ทั้งตอน dev (เปิด)
    และตอน deploy (ปิด) โดยไม่ต้องรู้ว่ากำลังรันอยู่ที่ไหน
    """
    from app.main import app

    expected = "/openapi.json" if settings.api_docs_enabled else None
    assert app.openapi_url == expected
    assert app.docs_url == ("/docs" if settings.api_docs_enabled else None)
    assert app.redoc_url == ("/redoc" if settings.api_docs_enabled else None)


@pytest.mark.parametrize("cookie_secure", [True, False])
async def test_cookie_login_works_under_both_cookie_secure_values(
    client: AsyncClient, user: User, monkeypatch, cookie_secure: bool
) -> None:
    """เทสต้องไม่สนใจว่า deployment ตั้ง COOKIE_SECURE ไว้เท่าไหร่

    เป็นไปได้เพราะ client fixture ยิงผ่าน https — cookie ที่มีแฟล็ก Secure
    จึงถูกส่งกลับตามปกติ ถ้าใครเปลี่ยน base_url กลับไปเป็น http เทสนี้จะแดงทันที
    ซึ่งเป็นสิ่งที่ต้องการ
    """
    monkeypatch.setattr(settings, "cookie_secure", cookie_secure)

    login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200

    me = await client.get("/api/auth/me")
    assert me.status_code == 200, (
        f"cookie ใช้ไม่ได้เมื่อ COOKIE_SECURE={cookie_secure} — "
        "แปลว่าชุดเทสผูกกับ config ของ deployment อีกแล้ว"
    )
    assert me.json()["email"] == user.email
