"""Pipeline: detect -> OCR/parse -> clean -> chunk -> embed -> เก็บลง DB

ทำงานใน Celery worker ที่ --concurrency=1 เพราะ GPU 6GB รับ OCR ได้ทีละหน้า
"""
import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, engine
from app.ingestion import embed as embedder
from app.ingestion.chunk import PageText, chunk_document
from app.ingestion.clean import clean_pages
from app.ingestion.detect import plan_document
from app.ingestion.ocr_typhoon import TyphoonOcrClient
from app.ingestion.parsers import extract_text
from app.ingestion.render import render_pdf_page
from app.llm import ollama_admin
from app.models.document import Chunk, Document, IngestionJob
from app.models.user import User
from app.quota import service as quota_service
from app.quota.page_count import PDF_MIMES
from app.retrieval.keywords import to_search_text
from app.worker import celery_app

log = logging.getLogger("app.ingestion")


async def _set_stage(
    session: AsyncSession, job: IngestionJob, stage: str, *, progress: int | None = None
) -> None:
    job.stage = stage
    if progress is not None:
        job.progress = progress
    await session.commit()


async def _collect_pages(
    session: AsyncSession,
    job: IngestionJob,
    document: Document,
    task_type: str | None = None,
) -> tuple[list[PageText], float]:
    """คืนข้อความรายหน้า และเวลาที่ใช้กับ GPU จริง

    task_type ส่งมาจาก reprocess เพื่อสั่ง OCR โหมดอื่นเฉพาะงานนี้
    (structure สำหรับเอกสารที่มีตาราง) โดยไม่กระทบค่าตั้งต้นของทั้งระบบ
    """
    path = Path(document.storage_path)
    gpu_seconds = 0.0

    if document.mime_type.lower().split(";")[0] not in PDF_MIMES:
        if document.mime_type.startswith("image/"):
            await _set_stage(session, job, "ocr")
            started = time.perf_counter()
            result = await TyphoonOcrClient().ocr_image_bytes(
                path.read_bytes(), mime_type=document.mime_type, task_type=task_type
            )
            gpu_seconds += time.perf_counter() - started
            job.pages_done = 1
            await session.commit()
            return [PageText(page_no=1, text=result.text, source="ocr")], gpu_seconds

        await _set_stage(session, job, "parse")
        return [PageText(page_no=1, text=extract_text(path, document.mime_type))], 0.0

    plan = plan_document(path, document.mime_type)
    job.pages_total = plan.total_pages
    await session.commit()

    ocr_client = TyphoonOcrClient()
    pages: list[PageText] = []

    for page in plan.pages:
        if page.needs_ocr:
            await _set_stage(session, job, "ocr")
            image = render_pdf_page(path, page.page_no)
            started = time.perf_counter()
            result = await ocr_client.ocr_image_bytes(
                image, mime_type="image/png", task_type=task_type
            )
            gpu_seconds += time.perf_counter() - started
            pages.append(PageText(page_no=page.page_no, text=result.text, source="ocr"))
        else:
            # หน้าที่มี text layer อยู่แล้วข้าม GPU ไปเลย — นี่คือที่มาของการประหยัดเวลา
            pages.append(PageText(page_no=page.page_no, text=page.text, source="parse"))

        job.pages_done = page.page_no
        job.progress = int(100 * page.page_no / max(1, plan.total_pages))
        await session.commit()

    return pages, gpu_seconds


async def _store_chunks(
    session: AsyncSession, document: Document, pages: list[PageText]
) -> int:
    cleaned = clean_pages([p.text for p in pages])
    prepared = [
        PageText(page_no=p.page_no, text=text, source=p.source)
        for p, text in zip(pages, cleaned, strict=True)
    ]

    chunks = chunk_document(prepared, doc_title=Path(document.filename).stem)
    if not chunks:
        return 0

    texts = [c.text for c in chunks]
    vectors = await embedder.embed_texts(texts)
    token_counts = await embedder.count_tokens(texts)

    for chunk, vector, tokens in zip(chunks, vectors, token_counts, strict=True):
        session.add(
            Chunk(
                document_id=document.id,
                owner_id=document.owner_id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                page_no=chunk.page_no,
                token_count=tokens,
                source=chunk.source,
                embedding=vector,
                # ตัดคำไว้ตั้งแต่ตอน ingest — ทำตอน query จะช้าและ index ใช้ไม่ได้
                search_text=to_search_text(chunk.text),
                meta={"heading": chunk.heading} if chunk.heading else {},
            )
        )

    await session.commit()
    return len(chunks)


async def _run(job_id: uuid.UUID, task_type: str | None = None, session_factory=None) -> dict:
    """รัน pipeline ของงานหนึ่งงาน

    รับ session_factory เข้ามาได้เพื่อให้เทสชี้ไปฐานทดสอบได้
    เดิมผูกกับ SessionLocal ตายตัว ทำให้เส้นทาง error ทั้งเส้นทดสอบไม่ได้เลย
    """
    factory = session_factory or SessionLocal

    async with factory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            return {"status": "missing_job", "job_id": str(job_id)}

        document = await session.get(Document, job.document_id)
        if document is None:
            job.stage = "failed"
            job.error = "ไม่พบเอกสาร"
            await session.commit()
            return {"status": "missing_document"}

        owner = await session.get(User, document.owner_id)

        job.started_at = datetime.now(UTC)
        # จับไว้ตั้งแต่ต้นงาน: ถ้าโมเดลหล่นไป CPU ทุกตัวเลขเวลาหลังจากนี้จะเพี้ยน
        # และเป็นสาเหตุอันดับหนึ่งที่ OCR ช้าผิดปกติ
        job.processor_note = await ollama_admin.processor_note()
        document.status = "processing"
        await _set_stage(session, job, "detect", progress=0)

        try:
            pages, gpu_seconds = await _collect_pages(session, job, document, task_type)

            await _set_stage(session, job, "chunk", progress=90)
            chunk_count = await _store_chunks(session, document, pages)

            await _set_stage(session, job, "embed", progress=95)

            actual_pages = len(pages)
            document.page_count = actual_pages
            document.page_count_estimated = False
            document.status = "ready"

            if owner is not None:
                await quota_service.commit(session, owner, document.id, actual_pages)

            job.gpu_seconds = gpu_seconds
            job.pages_done = actual_pages
            job.finished_at = datetime.now(UTC)
            await _set_stage(session, job, "done", progress=100)

            return {
                "status": "done",
                "chunks": chunk_count,
                "pages": actual_pages,
                "gpu_seconds": round(gpu_seconds, 1),
            }

        except Exception as exc:  # noqa: BLE001
            log.exception("ingestion ล้มเหลว job=%s", job_id)
            await session.rollback()

            job = await session.get(IngestionJob, job_id)
            document = await session.get(Document, job.document_id) if job else None
            if job is not None:
                job.error = f"{type(exc).__name__}: {exc}"[:2000]
                job.finished_at = datetime.now(UTC)
                job.stage = "failed"
            if document is not None:
                document.status = "failed"

            # คืนโควตาเฉพาะกรณีที่ยังไม่ได้แตะ GPU — ถ้าผ่าน OCR ไปแล้วทรัพยากร
            # ถูกใช้ไปจริง ถ้าคืนให้ user จะอัป-ลบ-อัปวนไม่จบและยึดคิวได้ไม่จำกัด
            touched_gpu = bool(job and job.pages_done)
            if owner is not None and job is not None:
                await quota_service.release(
                    session,
                    owner,
                    job.document_id,
                    note=f"failed at {job.stage}",
                    refund_document=not touched_gpu,
                )

            await session.commit()
            return {"status": "failed", "error": str(exc)}


async def _run_then_release_pool(job_id: uuid.UUID, task_type: str | None) -> dict:
    """รันงานแล้วคืน connection ทั้งหมดก่อนปิด event loop

    ต้องทำเพราะ connection ของ asyncpg ผูกกับ event loop ที่สร้างมัน
    แต่ ingest_document เรียก asyncio.run ซึ่งสร้าง loop ใหม่ทุกครั้ง
    ถ้าไม่ทิ้ง pool งานถัดไปจะหยิบ connection ของ loop ที่ตายไปแล้วมาใช้
    แล้วล้มด้วย "got Future attached to a different loop"

    อาการที่เห็นคือ **เอกสารแรกหลัง worker เริ่มสำเร็จ ตัวที่สองพัง** ซึ่งดูเหมือน
    ปัญหาของไฟล์นั้นทั้งที่เป็นปัญหาของ pool · dispose ต้องอยู่ใน loop เดียวกับที่
    เปิด connection ไว้ จึงเรียกที่นี่ ไม่ใช่หลัง asyncio.run คืนค่า

    ราคาที่จ่ายคือทุกงานเริ่มด้วยการต่อ DB ใหม่ ซึ่งกินเวลาหลัก ~10 มิลลิวินาที
    เทียบกับ OCR ที่ใช้หลายวินาทีต่อหน้าแล้วไม่มีนัยสำคัญ
    """
    try:
        return await _run(job_id, task_type)
    finally:
        await engine.dispose()


@celery_app.task(name="app.ingestion.tasks.ingest_document", bind=True)
def ingest_document(self, job_id: str, task_type: str | None = None) -> dict:  # noqa: ANN001, ARG001
    return asyncio.run(_run_then_release_pool(uuid.UUID(job_id), task_type))
