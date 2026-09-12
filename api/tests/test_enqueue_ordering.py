"""เทสลำดับ commit กับการส่งงานเข้าคิว

worker อ่าน database คนละคอนเนกชันกับ API ถ้าส่งงานเข้าคิวตั้งแต่ยังไม่ commit
worker อาจหยิบงานไปทำก่อนธุรกรรมจบ แล้วหาแถวงานไม่เจอ จบไปเงียบ ๆ ด้วยผล
missing_job ทิ้งเอกสารค้างสถานะ pending ตลอดกาลโดยไม่มีข้อความบอกใคร

เจอจริงตอนอัปเอกสาร 8 ไฟล์รวดเดียวแล้วหลุดไป 1 ไฟล์ · เทสนี้ไม่ได้จำลอง race
แต่ล็อกลำดับไว้ว่า commit ต้องมาก่อน enqueue เสมอ ซึ่งเป็นเงื่อนไขที่ทำให้ race หายไป
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion import queue as ingest_queue
from app.models.user import User
from tests.conftest import TEST_PASSWORD


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))


@pytest.fixture
def timeline(session: AsyncSession, monkeypatch):
    """บันทึกลำดับของ commit กับ enqueue ตามเวลาจริงที่เกิดขึ้น"""
    events: list[str] = []
    original_commit = session.commit

    async def recording_commit():
        await original_commit()
        events.append("commit")

    def recording_enqueue(job_id, *, queue, task_type=None):
        events.append("enqueue")
        return f"task-{job_id}"

    monkeypatch.setattr(session, "commit", recording_commit)
    monkeypatch.setattr(ingest_queue, "enqueue_ingestion", recording_enqueue)
    return events


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _assert_commit_precedes_every_enqueue(events: list[str]) -> None:
    assert "enqueue" in events, "ไม่มีการส่งงานเข้าคิวเลย เทสนี้จึงไม่ได้ตรวจอะไร"
    first_enqueue = events.index("enqueue")
    assert "commit" in events[:first_enqueue], (
        f"ส่งงานเข้าคิวก่อน commit — worker อาจหาแถวงานไม่เจอ · ลำดับที่ได้: {events}"
    )


async def test_single_upload_commits_before_enqueue(
    client: AsyncClient, user: User, timeline: list[str]
) -> None:
    headers = await _auth(client, user)
    resp = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("ระเบียบ.txt", "เนื้อหาทดสอบ".encode(), "text/plain")},
    )
    assert resp.status_code == 202, resp.text
    _assert_commit_precedes_every_enqueue(timeline)


async def test_bulk_upload_commits_before_any_enqueue(
    client: AsyncClient, admin: User, timeline: list[str]
) -> None:
    """เคสที่เจอบั๊กจริง — เดิมส่งเข้าคิวหลายงานแล้วค่อย commit ครั้งเดียวตอนจบ
    ช่องว่างจึงกว้างพอที่ worker จะชนะการแข่ง
    """
    headers = await _auth(client, admin)
    files = [
        ("files", (f"เอกสาร{i}.txt", f"เนื้อหาที่ {i}".encode(), "text/plain"))
        for i in range(5)
    ]
    resp = await client.post("/api/admin/documents/bulk", headers=headers, files=files)
    assert resp.status_code == 202, resp.text
    assert len(resp.json()["accepted"]) == 5

    _assert_commit_precedes_every_enqueue(timeline)
    # ทุกงานต้องอยู่หลัง commit ไม่ใช่แค่งานแรก
    assert timeline.index("commit") < timeline.index("enqueue")
    assert timeline.count("enqueue") == 5


async def test_reprocess_commits_before_enqueue(
    client: AsyncClient, session: AsyncSession, admin: User, timeline: list[str]
) -> None:
    from app.models.document import IngestionJob

    headers = await _auth(client, admin)
    upload = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("ระเบียบ.txt", "เนื้อหาทดสอบ".encode(), "text/plain")},
    )
    document_id = upload.json()["document"]["id"]

    # คิวปลอมไม่ได้รันงานให้ ต้องปิดงานแรกเองก่อน ไม่งั้น reprocess ตอบ 409
    # ว่ากำลังประมวลผลอยู่ ซึ่งถูกต้องแล้วแต่ไม่ใช่สิ่งที่เทสนี้ต้องการวัด
    job = await session.get(IngestionJob, uuid.UUID(upload.json()["job"]["id"]))
    job.stage = "done"
    await session.commit()
    timeline.clear()

    resp = await client.post(
        f"/api/admin/documents/{document_id}/reprocess", headers=headers, json={}
    )
    assert resp.status_code == 202, resp.text
    _assert_commit_precedes_every_enqueue(timeline)


async def test_job_row_is_readable_from_another_connection_after_upload(
    client: AsyncClient, user: User, timeline: list[str], make_session
) -> None:
    """ยืนยันผลลัพธ์ที่ต้องการจริง ๆ ไม่ใช่แค่ลำดับการเรียก

    worker เปิดคอนเนกชันของตัวเอง แถวงานต้องมองเห็นได้จากที่นั่น
    """
    from app.models.document import IngestionJob

    headers = await _auth(client, user)
    resp = await client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("ระเบียบ.txt", "เนื้อหาทดสอบ".encode(), "text/plain")},
    )
    job_id = uuid.UUID(resp.json()["job"]["id"])

    other = make_session()
    assert await other.get(IngestionJob, job_id) is not None, (
        "worker จะหาแถวงานไม่เจอ แล้วจบไปเงียบ ๆ ด้วยผล missing_job"
    )
