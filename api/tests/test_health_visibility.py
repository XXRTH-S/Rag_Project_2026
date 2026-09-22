"""/health/deep ต้องตอบทุกคนได้ แต่ตอบไม่เท่ากัน

endpoint นี้ปิดด้วย auth ดื้อ ๆ ไม่ได้ เพราะ monitor ภายนอกและ check.ps1 ต้องเรียกได้
โดยไม่มี credential แต่เดิมมันแจกรุ่น pgvector ชื่อโมเดลทุกตัว รายชื่อ provider
สถานะ GPU และข้อความ exception ดิบให้คนที่ยังไม่ได้ล็อกอิน ซึ่งเป็นแผนที่ชั้นดี
ให้คนที่จะลองโจมตี — ยิ่งเมื่อเปิด tunnel ให้คนนอกเข้ามาดู (21 ก.ย. 2026)
"""
import httpx
import pytest
from httpx import AsyncClient

from app.models.user import User
from app.routers import health
from tests.conftest import TEST_PASSWORD

SECRET_FIELDS = ("tier", "gpu")


async def test_anonymous_sees_only_pass_or_fail(client: AsyncClient) -> None:
    resp = await client.get("/health/deep")
    assert resp.status_code in (200, 503)

    body = resp.json()
    assert set(body) == {"status", "checks"}, f"มีฟิลด์เกินมา: {sorted(body)}"

    for field in SECRET_FIELDS:
        assert field not in body, f"{field} ไม่ควรหลุดไปถึงผู้เรียกที่ไม่ได้ล็อกอิน"

    for name, check in body["checks"].items():
        assert set(check) == {"ok"}, f"check {name} แจกรายละเอียดเกินจำเป็น: {sorted(check)}"


async def test_ordinary_user_does_not_get_the_detail_either(
    client: AsyncClient, user: User
) -> None:
    """ล็อกอินแล้วแต่ไม่ใช่ admin ก็ยังไม่ควรเห็นผังของระบบ"""
    await client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})

    body = (await client.get("/health/deep")).json()
    assert set(body) == {"status", "checks"}


async def test_admin_still_gets_everything(client: AsyncClient, admin: User) -> None:
    """คนที่ต้องใช้ข้อมูลนี้ซ่อมระบบต้องยังเห็นครบเหมือนเดิม"""
    await client.post("/api/auth/login", json={"email": admin.email, "password": TEST_PASSWORD})

    body = (await client.get("/health/deep")).json()
    assert body["tier"]
    assert "gpu" in body
    assert "pgvector" in body["checks"]["postgres"]


@pytest.mark.parametrize(
    "leaky",
    [
        httpx.ConnectError("[Errno -2] Name or service not known: embeddings:8080"),
        OSError("could not connect to server: postgres:5432 as user rag"),
    ],
)
def test_exception_text_never_reaches_the_response(leaky: Exception) -> None:
    """ข้อความ exception มีชื่อโฮสต์ พอร์ต และพาธไฟล์ — ต้องเหลือแค่รหัสอ้างอิง"""
    detail = health._opaque("embeddings", leaky)

    assert "รหัสอ้างอิง" in detail
    for leak in ("embeddings:8080", "postgres:5432", "Errno", "rag"):
        assert leak not in detail, f"ข้อความดิบ {leak!r} หลุดออกมากับคำตอบ"
