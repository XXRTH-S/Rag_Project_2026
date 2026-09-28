import logging
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.core.db import get_session
from app.core.deps import get_current_user, require_ingestion
from app.ingestion import queue as ingest_queue
from app.ingestion.detect import plan_document
from app.models.document import Document, IngestionJob
from app.models.user import User
from app.quota import service as quota_service
from app.quota.page_count import UnsupportedFileType, count_pages
from app.schemas.base import Page
from app.schemas.documents import DocumentOut, JobOut, UploadAccepted

router = APIRouter(prefix="/api/documents", tags=["documents"])
log = logging.getLogger("app.documents")


def _detect_mime(head: bytes, filename: str) -> str:
    """เชื่อเนื้อไฟล์ ไม่เชื่อนามสกุล — user เปลี่ยนนามสกุลได้"""
    import magic

    mime = magic.from_buffer(head, mime=True)
    # libmagic มอง docx/xlsx เป็น zip เพราะมันคือ zip จริง ๆ ต้องดูนามสกุลช่วย
    if mime == "application/zip" and filename.lower().endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # รวม MIME ของข้อความย่อยเป็นชนิดที่ parser รองรับ เช่น text/x-c เป็นข้อความธรรมดา
    if mime.startswith("text/") and mime not in {"text/html"}:
        return "text/markdown" if filename.lower().endswith(".md") else "text/plain"
    return mime


def _storage_path(owner_id: uuid.UUID, document_id: uuid.UUID, filename: str) -> Path:
    suffix = Path(filename).suffix[:16]
    directory = Path(settings.upload_dir) / str(owner_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{document_id}{suffix}"


# อ่านทีละ 1 MB — ใหญ่พอให้ไม่ช้า เล็กพอให้หยุดได้เร็วเมื่อไฟล์เกินเพดาน
_READ_CHUNK = 1024 * 1024


async def save_upload_within_limit(
    upload: UploadFile, destination: Path, limit: int
) -> tuple[bytes, int]:
    """เขียนไฟล์ลงดิสก์ทีละส่วน พร้อมนับขนาดไปด้วย คืน (ส่วนหัว, ขนาดรวม)

    ห้ามใช้ `await upload.read()` อ่านทั้งก้อน เพราะมันดึงไฟล์ทั้งไฟล์เข้า RAM
    *ก่อน* ที่เราจะได้ตรวจขนาด — ส่งไฟล์ 5 GB มาก็กิน RAM 5 GB ทันที
    บนเครื่องตัวเดียวที่แชร์กับ Postgres และ Ollama นั่นคือการล้มทั้งระบบ
    ด้วยคำขอเดียว

    อ่านทีละส่วนแล้วหยุดทันทีที่เกินเพดาน หน่วยความจำจึงคงที่ไม่ว่าไฟล์จะใหญ่แค่ไหน
    และลบไฟล์ที่เขียนค้างไว้ก่อนโยน error ไม่ให้ดิสก์ค่อย ๆ เต็มจากคำขอที่ถูกปฏิเสธ
    """
    total = 0
    head = b""
    try:
        with destination.open("wb") as sink:
            while True:
                block = await upload.read(_READ_CHUNK)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"ไฟล์ใหญ่เกิน {settings.max_upload_mb} MB",
                    )
                if len(head) < 4096:
                    head += block[: 4096 - len(head)]
                sink.write(block)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ไฟล์ว่าง")

    return head, total


@router.post(
    "",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_ingestion)],
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    collection: str = Query("default", max_length=64),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # กันการยิงอัปโหลดรัว ๆ จนคิว OCR ตัน ก่อนที่โควตารายวันจะทันได้ทำงาน
    await ratelimit.enforce(
        request,
        scope="upload",
        limit=settings.rate_limit_upload_per_hour,
        window_seconds=3600,
        subject=str(user.id),
    )

    limit = settings.max_upload_mb * 1024 * 1024
    document_id = uuid.uuid4()
    path = _storage_path(user.id, document_id, file.filename or "upload")
    head, size_bytes = await save_upload_within_limit(file, path, limit)
    mime = _detect_mime(head, file.filename or "")

    try:
        # นับหน้า *ก่อน* เข้าคิว — ถ้ารอนับหลัง OCR user จะเผา GPU ไปเป็นชั่วโมง
        # ก่อนได้รู้ว่าเกินโควตา
        estimate = count_pages(path, mime)
        plan = plan_document(path, mime)
    except UnsupportedFileType as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    document = Document(
        id=document_id,
        owner_id=user.id,
        filename=file.filename or "upload",
        mime_type=mime,
        storage_path=str(path),
        size_bytes=size_bytes,
        collection=collection,
        status="pending",
        page_count=estimate.pages,
        page_count_estimated=estimate.estimated,
        ocr_page_count=plan.ocr_page_count,
    )
    session.add(document)
    await session.flush()  # ต้องมีแถวเอกสารก่อน เพราะ quota_events มี FK มาที่นี่

    try:
        await quota_service.reserve(session, user, document_id, estimate.pages)
    except quota_service.QuotaExceeded as exc:
        await session.rollback()
        path.unlink(missing_ok=True)
        return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content=exc.to_dict())

    job = IngestionJob(
        document_id=document_id,
        stage="queued",
        pages_total=plan.total_pages,
        queue=ingest_queue.queue_for(user.is_admin),
    )
    session.add(job)
    # commit ก่อนส่งเข้าคิว เพื่อให้ worker มองเห็นแถวงานจากอีก connection
    await session.commit()

    try:
        job.celery_task_id = ingest_queue.enqueue_ingestion(job.id, queue=job.queue)
    except Exception as exc:
        # broker ล่ม = งานไม่มีวันถูกหยิบ ต้องคืนโควตาทันที ไม่ใช่ปล่อยให้ค้าง
        log.exception("ส่งงานเข้าคิวไม่สำเร็จ")
        await quota_service.release(session, user, document_id, note="enqueue failed")
        job.stage = "failed"
        job.error = f"ส่งงานเข้าคิวไม่สำเร็จ: {exc}"
        document.status = "failed"
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "ระบบคิวไม่พร้อม ลองใหม่อีกครั้ง"
        ) from exc

    await session.commit()

    return UploadAccepted(
        document=DocumentOut.model_validate(document),
        job=JobOut.model_validate(job),
        estimated_seconds=plan.estimated_seconds,
        ocr_pages=plan.ocr_page_count,
    )


@router.get("", response_model=Page[DocumentOut])
async def list_documents(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # กรองสิทธิ์ที่ระดับ SQL ไม่ใช่กรองหลังดึงมาแล้ว
    def scoped(stmt):
        return stmt if user.is_admin else stmt.where(Document.owner_id == user.id)

    total = (
        await session.execute(scoped(select(func.count()).select_from(Document)))
    ).scalar_one()

    rows = (
        await session.execute(
            scoped(select(Document))
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return Page[DocumentOut](
        items=[DocumentOut.model_validate(d) for d in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    document = await session.get(Document, document_id)
    if document is None or (not user.is_admin and document.owner_id != user.id):
        # ตอบ 404 เหมือนกันทั้งกรณีไม่มีจริงและไม่มีสิทธิ์ ไม่ให้เดาได้ว่ามีเอกสารอยู่
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบเอกสาร")
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    document = await session.get(Document, document_id)
    if document is None or (not user.is_admin and document.owner_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบเอกสาร")

    owner = await session.get(User, document.owner_id)

    # คืนโควตาเฉพาะเอกสารที่ยังไม่ใช้ GPU และลบในวันอัปโหลด
    # ไม่คืนหลัง OCR หรือข้ามวัน เพื่อป้องกันการอัปโหลดวนและยอดโควตาคลาดเคลื่อน
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .order_by(IngestionJob.queued_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()

    touched_gpu = document.ocr_page_count > 0 and bool(job and job.pages_done)
    same_day = document.created_at.astimezone(settings.tz).date() == settings.today()

    if owner is not None and same_day and not touched_gpu:
        await quota_service.release(session, owner, document_id, note="user deleted")

    path = Path(document.storage_path)
    # ลบไฟล์ก่อน commit ไม่ได้ ถ้า transaction ล้มจะเหลือแถวที่ชี้ไปไฟล์ที่หายแล้ว
    await session.delete(document)  # chunks/jobs หายตาม ON DELETE CASCADE
    await session.commit()

    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        # ลบแถวไปแล้ว ไฟล์ค้างไม่ทำให้ระบบพัง แค่กินดิสก์
        log.warning("ลบไฟล์ %s ไม่สำเร็จ: %s", path, exc)


@router.get("/{document_id}/job", response_model=JobOut)
async def get_job(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    document = await session.get(Document, document_id)
    if document is None or (not user.is_admin and document.owner_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบเอกสาร")

    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .order_by(IngestionJob.queued_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ยังไม่มีงานสำหรับเอกสารนี้")
    return job
