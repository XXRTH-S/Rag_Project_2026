"""เทสการลบเอกสารและกติกาการคืนโควตา

กติกา (PLAN.md ข้อ 8.2): คืนโควตาเฉพาะเอกสารที่ยังไม่ได้ใช้ GPU และลบในวันเดียวกัน
ถ้าคืนให้ทุกกรณี user จะอัป-ลบ-อัปวนได้ไม่จำกัดและยึดคิว GPU ทั้งวันโดยไม่เสียโควตา
"""
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion import queue as ingest_queue
from app.models.document import Chunk, Document, IngestionJob
from app.models.user import User
from tests.conftest import TEST_PASSWORD


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch):
    monkeypatch.setattr(ingest_queue, "enqueue_ingestion", lambda job_id, *, queue: "task")


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _upload(client: AsyncClient, headers: dict[str, str], name: str = "a.txt") -> str:
    resp = await client.post(
        "/api/documents", headers=headers, files={"file": (name, b"content here", "text/plain")}
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["document"]["id"]


async def test_delete_removes_document_and_file(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    headers = await _auth(client, user)
    document_id = await _upload(client, headers)

    stored = await session.get(Document, uuid.UUID(document_id))
    path = Path(stored.storage_path)
    assert path.exists()

    resp = await client.delete(f"/api/documents/{document_id}", headers=headers)
    assert resp.status_code == 204

    assert await session.get(Document, uuid.UUID(document_id)) is None
    assert not path.exists()


async def test_delete_refunds_quota_when_gpu_was_not_used(
    client: AsyncClient, user: User
) -> None:
    headers = await _auth(client, user)
    document_id = await _upload(client, headers)

    before = (await client.get("/api/me/quota", headers=headers)).json()
    assert before["documents"]["used"] == 1

    await client.delete(f"/api/documents/{document_id}", headers=headers)

    after = (await client.get("/api/me/quota", headers=headers)).json()
    assert after["documents"]["used"] == 0
    assert after["pages"]["used"] == 0


async def test_delete_does_not_refund_after_ocr_ran(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """ทรัพยากร GPU ถูกใช้ไปแล้ว ถ้าคืนโควตาจะเปิดช่องให้อัป-ลบ-อัปวนไม่จบ"""
    headers = await _auth(client, user)
    document_id = await _upload(client, headers)

    document = await session.get(Document, uuid.UUID(document_id))
    document.ocr_page_count = 1
    job = (
        await session.execute(
            select(IngestionJob).where(IngestionJob.document_id == document.id)
        )
    ).scalar_one()
    job.pages_done = 1
    await session.commit()

    await client.delete(f"/api/documents/{document_id}", headers=headers)

    after = (await client.get("/api/me/quota", headers=headers)).json()
    assert after["documents"]["used"] == 1, "ผ่าน OCR แล้วต้องไม่คืนโควตา"


async def test_delete_does_not_refund_across_days(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """โควตารีเซ็ตรายวันอยู่แล้ว การคืนย้อนหลังจะทำให้ยอดวันนี้เกินเพดาน"""
    headers = await _auth(client, user)
    document_id = await _upload(client, headers)

    document = await session.get(Document, uuid.UUID(document_id))
    document.created_at = document.created_at - timedelta(days=2)
    await session.commit()

    await client.delete(f"/api/documents/{document_id}", headers=headers)

    after = (await client.get("/api/me/quota", headers=headers)).json()
    assert after["documents"]["used"] == 1


async def test_delete_removes_chunks(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    headers = await _auth(client, user)
    document_id = await _upload(client, headers)

    session.add(
        Chunk(
            document_id=uuid.UUID(document_id),
            owner_id=user.id,
            ordinal=0,
            text="เนื้อหา",
            page_no=1,
            source="parse",
        )
    )
    await session.commit()

    await client.delete(f"/api/documents/{document_id}", headers=headers)

    remaining = await session.execute(select(func.count()).select_from(Chunk))
    assert remaining.scalar_one() == 0


async def test_cannot_delete_someone_elses_document(
    client: AsyncClient, user: User, admin: User
) -> None:
    admin_headers = await _auth(client, admin)
    document_id = await _upload(client, admin_headers, "secret.txt")

    user_headers = await _auth(client, user)
    resp = await client.delete(f"/api/documents/{document_id}", headers=user_headers)
    # 404 ไม่ใช่ 403 — ไม่ให้เดาได้ว่ามีเอกสารนี้อยู่จริง
    assert resp.status_code == 404


async def test_admin_can_delete_any_document(
    client: AsyncClient, user: User, admin: User
) -> None:
    user_headers = await _auth(client, user)
    document_id = await _upload(client, user_headers)

    admin_headers = await _auth(client, admin)
    resp = await client.delete(f"/api/documents/{document_id}", headers=admin_headers)
    assert resp.status_code == 204


async def test_delete_requires_authentication(client: AsyncClient) -> None:
    resp = await client.delete(f"/api/documents/{uuid.uuid4()}")
    assert resp.status_code == 401
