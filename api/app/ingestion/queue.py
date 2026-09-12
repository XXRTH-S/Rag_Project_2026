"""ส่งงานเข้าคิว — แยกออกมาเป็นฟังก์ชันเดียวเพื่อให้ router ไม่ผูกกับ Celery โดยตรง

ทำให้เทส endpoint อัปโหลดได้โดยไม่ต้องมี broker และสลับ backend คิวได้ทีหลัง
"""
import uuid

QUEUE_USER = "ocr_user"
QUEUE_ADMIN = "ocr_admin"


def queue_for(is_admin: bool) -> str:
    """แยกคิว admin ออกจาก user — งาน bulk ของ admin ต้องไม่ดองงานของ user

    บนการ์ด 6GB ที่ทำได้ทีละหน้า ถ้าใช้คิวเดียวกัน admin อัป 100 ไฟล์ทีเดียว
    user คนอื่นจะรอข้ามวัน
    """
    return QUEUE_ADMIN if is_admin else QUEUE_USER


def enqueue_ingestion(
    job_id: uuid.UUID, *, queue: str, task_type: str | None = None
) -> str | None:
    """ส่งงานเข้าคิว

    task_type ใช้ตอน reprocess เพื่อสั่ง OCR ด้วยโหมดอื่น (default / structure)
    โดยไม่ต้องแก้ค่าใน .env ซึ่งจะกระทบงานอื่นทั้งระบบ
    """
    from app.ingestion.tasks import ingest_document

    result = ingest_document.apply_async(args=[str(job_id), task_type], queue=queue)
    return result.id
