"""endpoint ฝั่ง admin สำหรับจัดการเอกสาร

reprocess: สั่ง OCR ใหม่เมื่อผลไม่ดี — เป็นเรื่องปกติกับเอกสารสแกน
  เอกสารที่มีตารางเยอะควรใช้ task_type=structure ส่วนเอกสารทั่วไปใช้ default
  ถ้าไม่มีทางสั่งใหม่ ทางเดียวคือลบแล้วอัปใหม่ ซึ่งเสียโควตาและเสียประวัติ

bulk: admin อัปหลายไฟล์พร้อมกันโดยไม่นับโควตา — ใช้ตอนตั้งคลังความรู้ครั้งแรก
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.deps import require_admin
from app.ingestion import queue as ingest_queue
from app.ingestion.detect import plan_document
from app.models.document import Chunk, Document, IngestionJob
from app.models.user import User
from app.quota.page_count import UnsupportedFileType, count_pages
from app.routers.documents import _detect_mime, _storage_path
from app.schemas.documents import DocumentOut, JobOut

router = APIRouter(prefix="/api/admin/documents", tags=["admin-documents"])
log = logging.getLogger("app.admin.documents")


class ReprocessRequest(BaseModel):
    # default = เอกสารทั่วไป · structure = มีตาราง/ฟอร์ม
    task_type: str | None = Field(default=None, pattern="^(default|structure)$")


class BulkResult(BaseModel):
    accepted: list[DocumentOut]
    rejected: list[dict]


@router.post("/{document_id}/reprocess", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(
    document_id: uuid.UUID,
    payload: ReprocessRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """สั่งประมวลผลเอกสารเดิมใหม่ โดยไม่คิดโควตาซ้ำ

    ไม่คิดโควตาเพราะ user จ่ายไปแล้วตอนอัปโหลดครั้งแรก การที่ผล OCR ไม่ดี
    เป็นข้อจำกัดของระบบ ไม่ใช่ความผิดของ user
    """
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบเอกสาร")

    from pathlib import Path

    if not Path(document.storage_path).exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "ไฟล์ต้นฉบับหายไปแล้ว ประมวลผลใหม่ไม่ได้ ต้องอัปโหลดใหม่",
        )

    running = (
        await session.execute(
            select(IngestionJob)
            .where(
                IngestionJob.document_id == document_id,
                IngestionJob.stage.not_in(("done", "failed")),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if running is not None:
        # งานที่เข้าคิวไว้แต่ไม่เคยถูกหยิบไปทำ (started_at ว่าง) แปลว่า worker
        # ตายหรือรีสตาร์ทระหว่างทาง แถวนั้นจะค้างอยู่ตลอดไปเพราะไม่มีใครมาปิดให้
        # ผลคือเอกสารนั้น reprocess ไม่ได้อีกเลย ทั้งที่ chunk ถูกลบไปแล้ว —
        # ทางออกเดียวคือเข้าไปแก้ SQL เอง ซึ่งไม่ควรเป็นวิธีกู้คืนของ admin
        #
        # เก็บกวาดเฉพาะเคสที่ "ไม่เคยเริ่ม" เท่านั้น · งานที่เริ่มแล้วค้างกลางทาง
        # แยกจากงานที่กำลังทำอยู่จริงไม่ได้ ถ้าไม่มี heartbeat — 500 หน้าใช้เวลา
        # เกินชั่วโมง การไปปิดมันทิ้งจะทำลายงานที่กำลังเดินอยู่
        stale_after = timedelta(minutes=settings.ingestion_stale_after_minutes)
        never_started = running.started_at is None
        waited_too_long = datetime.now(UTC) - running.queued_at > stale_after
        if not (never_started and waited_too_long):
            raise HTTPException(status.HTTP_409_CONFLICT, "เอกสารนี้กำลังประมวลผลอยู่แล้ว")

        log.warning("เก็บกวาดงานค้างคิว job=%s document=%s", running.id, document_id)
        running.stage = "failed"
        running.error = (
            f"ค้างอยู่ในคิวเกิน {settings.ingestion_stale_after_minutes} นาทีโดยไม่มี worker "
            "มารับงาน (worker น่าจะหยุดทำงาน) จึงถูกปิดเพื่อให้สั่งประมวลผลใหม่ได้"
        )
        running.finished_at = datetime.now(UTC)
        await session.flush()

    # ลบ chunk เดิมทิ้งก่อน ไม่งั้นจะได้ทั้งของเก่าและใหม่ปนกันใน retrieval
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))

    document.status = "pending"
    job = IngestionJob(
        document_id=document_id,
        stage="queued",
        pages_total=document.page_count,
        queue=ingest_queue.QUEUE_ADMIN,
    )
    session.add(job)
    # commit ก่อนส่งเข้าคิวด้วยเหตุผลเดียวกับ bulk — worker ต้องมองเห็นแถวงานได้
    await session.commit()

    task_type = payload.task_type or settings.typhoon_ocr_task_type
    try:
        job.celery_task_id = ingest_queue.enqueue_ingestion(
            job.id, queue=job.queue, task_type=task_type
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("ส่งงาน reprocess เข้าคิวไม่สำเร็จ")
        job.stage = "failed"
        job.error = f"ส่งงานเข้าคิวไม่สำเร็จ: {exc}"
        document.status = "failed"
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "ระบบคิวไม่พร้อม ลองใหม่อีกครั้ง"
        ) from exc

    await session.commit()
    return job


@router.post("/bulk", response_model=BulkResult, status_code=status.HTTP_202_ACCEPTED)
async def bulk_upload(
    files: list[UploadFile] = File(...),
    collection: str = Query("default", max_length=64),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """อัปหลายไฟล์ทีเดียว ไม่นับโควตา — ใช้ตอนตั้งคลังความรู้ครั้งแรก

    ไฟล์ที่มีปัญหาจะถูกข้ามและรายงานกลับ ไม่ทำให้ทั้งชุดล้ม
    เพราะอัปทีละสิบไฟล์แล้วล้มเพราะไฟล์เดียวคือประสบการณ์ที่แย่มาก
    """
    limit = settings.max_upload_mb * 1024 * 1024
    accepted: list[Document] = []
    # เก็บไว้ส่งเข้าคิวหลัง commit — ดูเหตุผลตรงจุดที่ commit
    queued: list[tuple[str, Document, IngestionJob]] = []
    rejected: list[dict] = []

    for upload in files:
        name = upload.filename or "upload"
        payload = await upload.read()

        if not payload:
            rejected.append({"filename": name, "reason": "ไฟล์ว่าง"})
            continue
        if len(payload) > limit:
            rejected.append({"filename": name, "reason": f"ใหญ่เกิน {settings.max_upload_mb} MB"})
            continue

        mime = _detect_mime(payload[:4096], name)
        document_id = uuid.uuid4()
        path = _storage_path(admin.id, document_id, name)
        path.write_bytes(payload)

        try:
            estimate = count_pages(path, mime)
            plan = plan_document(path, mime)
        except UnsupportedFileType as exc:
            path.unlink(missing_ok=True)
            rejected.append({"filename": name, "reason": str(exc)})
            continue

        document = Document(
            id=document_id,
            owner_id=admin.id,
            filename=name,
            mime_type=mime,
            storage_path=str(path),
            size_bytes=len(payload),
            collection=collection,
            status="pending",
            page_count=estimate.pages,
            page_count_estimated=estimate.estimated,
            ocr_page_count=plan.ocr_page_count,
        )
        session.add(document)
        await session.flush()

        job = IngestionJob(
            document_id=document_id,
            stage="queued",
            pages_total=plan.total_pages,
            queue=ingest_queue.QUEUE_ADMIN,
        )
        session.add(job)
        await session.flush()
        queued.append((name, document, job))

    # commit ให้ครบทุกแถวก่อน แล้วค่อยส่งเข้าคิว — ห้ามสลับลำดับ
    # worker อ่านจากคอนเนกชันคนละตัว ถ้าส่งเข้าคิวตั้งแต่ยังไม่ commit
    # มันอาจหยิบงานไปทำก่อนธุรกรรมนี้จบ แล้วหาแถวงานไม่เจอ จบไปเงียบ ๆ
    # ด้วยผล missing_job ทิ้งเอกสารค้างสถานะ pending ตลอดกาล
    #
    # เคสนี้แย่กว่าอัปทีละไฟล์ เพราะส่งเข้าคิวหลายงานแล้วค่อย commit ครั้งเดียว
    # ช่องว่างจึงกว้างพอที่จะแพ้จริง — อัป 8 ไฟล์รวดเดียวแล้วหลุดไป 1 ไฟล์
    await session.commit()

    for name, document, job in queued:
        try:
            job.celery_task_id = ingest_queue.enqueue_ingestion(job.id, queue=job.queue)
        except Exception as exc:  # noqa: BLE001
            log.exception("ส่งงาน bulk เข้าคิวไม่สำเร็จ: %s", name)
            job.stage = "failed"
            job.error = f"ส่งงานเข้าคิวไม่สำเร็จ: {exc}"
            document.status = "failed"
            rejected.append({"filename": name, "reason": "ระบบคิวไม่พร้อม"})
            continue

        accepted.append(document)

    await session.commit()

    return BulkResult(
        accepted=[DocumentOut.model_validate(d) for d in accepted],
        rejected=rejected,
    )
