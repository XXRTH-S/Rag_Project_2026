"""เทสการจำกัดขนาดไฟล์อัปโหลด

เดิมโค้ดเรียก `await file.read()` อ่านทั้งไฟล์เข้าหน่วยความจำ *ก่อน* เทียบกับเพดาน
ส่งไฟล์ 5 GB มาก็กิน RAM 5 GB ทันทีแล้วค่อยปฏิเสธ — บนเครื่องตัวเดียวที่แชร์กับ
Postgres และ Ollama นั่นคือการล้มทั้งระบบด้วยคำขอเดียว
"""
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.ingestion import queue as ingest_queue
from app.models.user import User
from tests.conftest import TEST_PASSWORD


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch):
    monkeypatch.setattr(ingest_queue, "enqueue_ingestion", lambda *a, **k: "fake-task-id")


@pytest.fixture
def small_limit(monkeypatch):
    """เพดาน 1 MB เพื่อไม่ต้องสร้างไฟล์ทดสอบขนาดจริง"""
    monkeypatch.setattr(settings, "max_upload_mb", 1)


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_oversized_upload_is_rejected(
    client: AsyncClient, user: User, small_limit
) -> None:
    headers = await _auth(client, user)
    too_big = b"x" * (2 * 1024 * 1024)

    resp = await client.post(
        "/api/documents", headers=headers, files={"file": ("ใหญ่.txt", too_big, "text/plain")}
    )
    assert resp.status_code == 413
    assert "ใหญ่เกิน" in resp.text


async def test_rejected_upload_leaves_no_file_behind(
    client: AsyncClient, user: User, small_limit, isolated_uploads
) -> None:
    """ไฟล์ที่เขียนค้างต้องถูกลบ ไม่งั้นดิสก์ค่อย ๆ เต็มจากคำขอที่ถูกปฏิเสธ
    ซึ่งเป็นอีกทางหนึ่งที่ยิงให้ระบบล่มได้โดยไม่ต้องผ่านโควตาเลย
    """
    headers = await _auth(client, user)
    await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("ใหญ่.txt", b"x" * (2 * 1024 * 1024), "text/plain")},
    )

    leftovers = [p for p in isolated_uploads.rglob("*") if p.is_file()]
    assert leftovers == [], f"มีไฟล์ค้างอยู่: {leftovers}"


async def test_empty_upload_is_rejected(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    resp = await client.post(
        "/api/documents", headers=headers, files={"file": ("ว่าง.txt", b"", "text/plain")}
    )
    assert resp.status_code == 400
    assert "ว่าง" in resp.text


async def test_normal_upload_still_records_the_real_size(
    client: AsyncClient, user: User
) -> None:
    """อ่านทีละส่วนแล้วต้องนับขนาดได้ถูกต้องเท่าเดิม ไม่ใช่ได้ขนาดของส่วนสุดท้าย"""
    headers = await _auth(client, user)
    body = ("ระเบียบบริษัท " * 500).encode()

    resp = await client.post(
        "/api/documents", headers=headers, files={"file": ("ปกติ.txt", body, "text/plain")}
    )
    assert resp.status_code == 202
    assert resp.json()["document"]["size_bytes"] == len(body)


async def test_file_larger_than_one_read_chunk_is_saved_whole(
    client: AsyncClient, admin: User, isolated_uploads
) -> None:
    """ไฟล์ที่ใหญ่กว่าขนาดชิ้นที่อ่าน (1 MB) ต้องถูกเขียนครบทุกชิ้น
    ถ้าลูปเขียนผิดจะได้ไฟล์ที่ขาดหายโดยไม่มี error บอก

    ใช้บัญชี admin เพราะข้อความ 1 MB ถูกตีเป็นราว 354 หน้า ซึ่งเกินเพดาน
    200 หน้าต่อเอกสารของ user ธรรมดา — เทสนี้ต้องการวัดการอ่านไฟล์ ไม่ใช่โควตา
    """
    headers = await _auth(client, admin)
    body = b"a" * (1024 * 1024 + 12345)

    resp = await client.post(
        "/api/documents", headers=headers, files={"file": ("ยาว.txt", body, "text/plain")}
    )
    assert resp.status_code == 202
    assert resp.json()["document"]["size_bytes"] == len(body)

    saved = [p for p in isolated_uploads.rglob("*") if p.is_file()]
    assert len(saved) == 1
    assert saved[0].stat().st_size == len(body)


async def test_bulk_upload_skips_only_the_oversized_file(
    client: AsyncClient, admin: User, small_limit
) -> None:
    """ไฟล์ใหญ่เกินหนึ่งไฟล์ต้องไม่ทำให้ทั้งชุดล้ม"""
    headers = await _auth(client, admin)
    files = [
        ("files", ("เล็ก.txt", "เนื้อหาสั้น".encode(), "text/plain")),
        ("files", ("ใหญ่.txt", b"x" * (2 * 1024 * 1024), "text/plain")),
    ]

    resp = await client.post("/api/admin/documents/bulk", headers=headers, files=files)
    assert resp.status_code == 202
    body = resp.json()
    assert [d["filename"] for d in body["accepted"]] == ["เล็ก.txt"]
    assert [r["filename"] for r in body["rejected"]] == ["ใหญ่.txt"]
