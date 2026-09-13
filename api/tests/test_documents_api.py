import io
import uuid

import pytest
from httpx import AsyncClient
from pypdf import PdfWriter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion import queue as ingest_queue
from app.models.document import Document
from app.models.user import User
from tests.conftest import TEST_PASSWORD


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch):
    """ไม่ต้องมี broker ในเทส — คิวจริงถูกทดสอบตอนรัน worker"""
    sent: list[tuple[uuid.UUID, str]] = []

    def _enqueue(job_id, *, queue):
        sent.append((job_id, queue))
        return f"task-{job_id}"

    monkeypatch.setattr(ingest_queue, "enqueue_ingestion", _enqueue)
    return sent


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _blank_pdf_bytes(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def test_text_upload_is_accepted_and_needs_no_ocr(
    client: AsyncClient, user: User, fake_queue
) -> None:
    headers = await _auth(client, user)
    resp = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("คู่มือ.txt", "สวัสดีครับ นี่คือเอกสารทดสอบ".encode(), "text/plain")},
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["document"]["status"] == "pending"
    assert body["job"]["stage"] == "queued"
    assert body["job"]["queue"] == "ocr_user"
    # ไฟล์ข้อความไม่ต้องแตะ GPU เลย ETA จึงเป็นศูนย์
    assert body["ocr_pages"] == 0
    assert body["estimated_seconds"] == 0
    assert len(fake_queue) == 1


async def test_upload_decrements_quota(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("a.txt", b"hello world", "text/plain")},
    )

    quota = (await client.get("/api/me/quota", headers=headers)).json()
    assert quota["documents"]["used"] == 1
    assert quota["documents"]["remaining"] == settings.user_daily_document_limit - 1
    assert quota["pages"]["used"] == 1


async def test_scanned_pdf_reports_ocr_pages_and_eta(
    client: AsyncClient, user: User
) -> None:
    headers = await _auth(client, user)
    resp = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("scan.pdf", _blank_pdf_bytes(4), "application/pdf")},
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["ocr_pages"] == 4
    # UI ต้องบอก user ได้ว่ารอนานแค่ไหน ก่อนกดอัปโหลด ไม่ใช่ให้ลุ้นเอง
    assert body["estimated_seconds"] == 4 * settings.ocr_seconds_per_page
    assert body["job"]["pages_total"] == 4


async def test_admin_upload_goes_to_its_own_queue(client: AsyncClient, admin: User) -> None:
    headers = await _auth(client, admin)
    resp = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("bulk.txt", b"content", "text/plain")},
    )
    # งาน bulk ของ admin ต้องไม่ดองงานของ user ในคิวเดียวกัน
    assert resp.json()["job"]["queue"] == "ocr_admin"


async def test_exceeding_quota_returns_429_and_stores_nothing(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    headers = await _auth(client, user)
    for _ in range(settings.user_daily_document_limit):
        ok = await client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        assert ok.status_code == 202

    blocked = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("over.txt", b"hello", "text/plain")},
    )

    assert blocked.status_code == 429
    body = blocked.json()
    assert body["error"] == "quota_exceeded"
    assert body["documents"]["remaining"] == 0
    assert body["resets_at"]

    stored = await session.execute(select(func.count()).select_from(Document))
    assert stored.scalar_one() == settings.user_daily_document_limit


async def test_empty_file_is_rejected(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    resp = await client.post(
        "/api/documents", headers=headers, files={"file": ("empty.txt", b"", "text/plain")}
    )
    assert resp.status_code == 400


async def test_oversized_file_is_rejected(
    client: AsyncClient, user: User, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    headers = await _auth(client, user)
    resp = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("big.txt", b"x" * (2 * 1024 * 1024), "text/plain")},
    )
    assert resp.status_code == 413


async def test_users_only_see_their_own_documents(
    client: AsyncClient, session: AsyncSession, user: User, admin: User
) -> None:
    user_headers = await _auth(client, user)
    await client.post(
        "/api/documents",
        headers=user_headers,
        files={"file": ("mine.txt", b"content", "text/plain")},
    )

    admin_headers = await _auth(client, admin)
    await client.post(
        "/api/documents",
        headers=admin_headers,
        files={"file": ("theirs.txt", b"content", "text/plain")},
    )

    mine = (await client.get("/api/documents", headers=user_headers)).json()["items"]
    assert [d["filename"] for d in mine] == ["mine.txt"]

    all_docs = (await client.get("/api/documents", headers=admin_headers)).json()["items"]
    assert {d["filename"] for d in all_docs} == {"mine.txt", "theirs.txt"}


async def test_reading_someone_elses_document_returns_404(
    client: AsyncClient, user: User, admin: User
) -> None:
    admin_headers = await _auth(client, admin)
    created = await client.post(
        "/api/documents",
        headers=admin_headers,
        files={"file": ("secret.txt", b"content", "text/plain")},
    )
    document_id = created.json()["document"]["id"]

    user_headers = await _auth(client, user)
    resp = await client.get(f"/api/documents/{document_id}", headers=user_headers)
    # 404 ไม่ใช่ 403 — ไม่ให้เดาได้ว่ามีเอกสารนี้อยู่จริง
    assert resp.status_code == 404


async def test_job_status_is_reachable_from_the_document(
    client: AsyncClient, user: User
) -> None:
    headers = await _auth(client, user)
    created = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("a.txt", b"content", "text/plain")},
    )
    document_id = created.json()["document"]["id"]

    resp = await client.get(f"/api/documents/{document_id}/job", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["stage"] == "queued"


async def test_upload_requires_authentication(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/documents", files={"file": ("a.txt", b"content", "text/plain")}
    )
    assert resp.status_code == 401
