"""เทส endpoint ฝั่ง admin: reprocess และ bulk upload"""
import uuid
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
    sent: list[dict] = []

    def _enqueue(job_id, *, queue, task_type=None):
        sent.append({"job_id": job_id, "queue": queue, "task_type": task_type})
        return f"task-{job_id}"

    monkeypatch.setattr(ingest_queue, "enqueue_ingestion", _enqueue)
    return sent


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _upload(client: AsyncClient, headers: dict[str, str], name: str = "a.txt") -> str:
    resp = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": (name, "เนื้อหาทดสอบ".encode(), "text/plain")},
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["document"]["id"]


# reprocess


async def test_reprocess_creates_a_new_job(
    client: AsyncClient, session: AsyncSession, admin: User, fake_queue
) -> None:
    headers = await _auth(client, admin)
    document_id = await _upload(client, headers)

    # ปิดงานเดิมก่อน ไม่งั้นจะติดเงื่อนไข "กำลังประมวลผลอยู่"
    job = (
        await session.execute(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document_id))
        )
    ).scalar_one()
    job.stage = "done"
    await session.commit()

    resp = await client.post(
        f"/api/admin/documents/{document_id}/reprocess",
        headers=headers,
        json={"task_type": "structure"},
    )

    assert resp.status_code == 202, resp.text
    assert resp.json()["stage"] == "queued"
    assert fake_queue[-1]["task_type"] == "structure"
    assert fake_queue[-1]["queue"] == "ocr_admin"


async def test_reprocess_deletes_old_chunks(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """ถ้าไม่ลบ chunk เดิม retrieval จะเจอทั้งของเก่าและใหม่ปนกัน"""
    headers = await _auth(client, admin)
    document_id = await _upload(client, headers)

    job = (
        await session.execute(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document_id))
        )
    ).scalar_one()
    job.stage = "done"
    session.add(
        Chunk(
            document_id=uuid.UUID(document_id),
            owner_id=admin.id,
            ordinal=0,
            text="ข้อความเก่าจาก OCR รอบแรก",
            page_no=1,
            source="ocr",
        )
    )
    await session.commit()

    await client.post(
        f"/api/admin/documents/{document_id}/reprocess", headers=headers, json={}
    )

    remaining = await session.execute(select(func.count()).select_from(Chunk))
    assert remaining.scalar_one() == 0


async def test_reprocess_rejects_a_document_already_running(
    client: AsyncClient, admin: User
) -> None:
    headers = await _auth(client, admin)
    document_id = await _upload(client, headers)

    # งานแรกยังอยู่ในสถานะ queued
    resp = await client.post(
        f"/api/admin/documents/{document_id}/reprocess", headers=headers, json={}
    )
    assert resp.status_code == 409


async def test_reprocess_rejects_when_the_source_file_is_gone(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    headers = await _auth(client, admin)
    document_id = await _upload(client, headers)

    document = await session.get(Document, uuid.UUID(document_id))
    Path(document.storage_path).unlink()
    job = (
        await session.execute(
            select(IngestionJob).where(IngestionJob.document_id == document.id)
        )
    ).scalar_one()
    job.stage = "done"
    await session.commit()

    resp = await client.post(
        f"/api/admin/documents/{document_id}/reprocess", headers=headers, json={}
    )
    assert resp.status_code == 409
    assert "หายไป" in resp.json()["detail"]


async def test_reprocess_does_not_charge_quota_again(
    client: AsyncClient, session: AsyncSession, admin: User, user: User
) -> None:
    """user จ่ายโควตาไปแล้วตอนอัปครั้งแรก ผล OCR ไม่ดีไม่ใช่ความผิดของเขา"""
    user_headers = await _auth(client, user)
    document_id = await _upload(client, user_headers)

    before = (await client.get("/api/me/quota", headers=user_headers)).json()

    job = (
        await session.execute(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document_id))
        )
    ).scalar_one()
    job.stage = "done"
    await session.commit()

    admin_headers = await _auth(client, admin)
    await client.post(
        f"/api/admin/documents/{document_id}/reprocess", headers=admin_headers, json={}
    )

    after = (await client.get("/api/me/quota", headers=user_headers)).json()
    assert after["documents"]["used"] == before["documents"]["used"]
    assert after["pages"]["used"] == before["pages"]["used"]


async def test_reprocess_is_admin_only(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    document_id = await _upload(client, headers)
    resp = await client.post(
        f"/api/admin/documents/{document_id}/reprocess", headers=headers, json={}
    )
    assert resp.status_code == 403


async def test_reprocess_rejects_invalid_task_type(client: AsyncClient, admin: User) -> None:
    headers = await _auth(client, admin)
    document_id = await _upload(client, headers)
    resp = await client.post(
        f"/api/admin/documents/{document_id}/reprocess",
        headers=headers,
        json={"task_type": "ไม่มีโหมดนี้"},
    )
    assert resp.status_code == 422


# bulk


async def test_bulk_accepts_multiple_files(client: AsyncClient, admin: User) -> None:
    headers = await _auth(client, admin)
    resp = await client.post(
        "/api/admin/documents/bulk",
        headers=headers,
        files=[
            ("files", ("a.txt", "เอกสารหนึ่ง".encode(), "text/plain")),
            ("files", ("b.txt", "เอกสารสอง".encode(), "text/plain")),
        ],
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert len(body["accepted"]) == 2
    assert body["rejected"] == []


async def test_bulk_skips_bad_files_without_failing_the_batch(
    client: AsyncClient, admin: User
) -> None:
    """อัปสิบไฟล์แล้วล้มทั้งชุดเพราะไฟล์เดียว เป็นประสบการณ์ที่แย่มาก"""
    headers = await _auth(client, admin)
    resp = await client.post(
        "/api/admin/documents/bulk",
        headers=headers,
        files=[
            ("files", ("good.txt", "เนื้อหาปกติ".encode(), "text/plain")),
            ("files", ("empty.txt", b"", "text/plain")),
            ("files", ("movie.mp4", b"\x00\x00\x00\x20ftypmp42", "video/mp4")),
        ],
    )

    assert resp.status_code == 202
    body = resp.json()
    assert [d["filename"] for d in body["accepted"]] == ["good.txt"]
    assert {r["filename"] for r in body["rejected"]} == {"empty.txt", "movie.mp4"}


async def test_bulk_does_not_consume_admin_quota(client: AsyncClient, admin: User) -> None:
    headers = await _auth(client, admin)
    await client.post(
        "/api/admin/documents/bulk",
        headers=headers,
        files=[("files", ("a.txt", "เนื้อหา".encode(), "text/plain"))],
    )

    quota = (await client.get("/api/me/quota", headers=headers)).json()
    # ไม่มีการเรียก reserve เลย ยอดจึงเป็นศูนย์แม้อัปไปแล้ว
    assert quota["documents"]["used"] == 0


async def test_bulk_is_admin_only(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    resp = await client.post(
        "/api/admin/documents/bulk",
        headers=headers,
        files=[("files", ("a.txt", b"x", "text/plain"))],
    )
    assert resp.status_code == 403
