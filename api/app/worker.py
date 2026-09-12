"""Celery app

คิวแยกตั้งแต่วันแรก (PLAN.md ข้อ 14.1): งาน bulk ของ admin ต้องไม่ดองงานของ user
worker เดินด้วย --concurrency=1 เพราะ GPU 6GB รับ OCR ได้ทีละหน้าเท่านั้น
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery("rag_workshop", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.quota_timezone,
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        "app.ingestion.tasks.ingest_document": {"queue": "ocr_user"},
        "app.ingestion.tasks.ingest_document_admin": {"queue": "ocr_admin"},
    },
    task_time_limit=60 * 60 * 6,  # PDF 500 หน้าบน 3050 ใช้เวลาเป็นชั่วโมง
    task_soft_time_limit=60 * 60 * 5,
)

celery_app.autodiscover_tasks(["app.ingestion"])


@celery_app.task(name="app.ping")
def ping() -> str:
    return "pong"
