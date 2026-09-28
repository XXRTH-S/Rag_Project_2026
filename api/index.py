"""จุดเข้าของ Vercel Python runtime

Vercel มองหาไฟล์ใน `api/` แล้วรันเป็น serverless function ตัวหนึ่ง
ไฟล์นี้ไม่ทำอะไรเลยนอกจากส่งต่อแอป ASGI ตัวเดิม — ไม่มีโค้ดสาขาไหนที่
"เฉพาะ Vercel" เพราะความต่างทั้งหมดคุมด้วย environment variable

สิ่งที่ไม่ทำงานบน Vercel และเหตุผล (ดู INGESTION_ENABLED ใน app/core/config.py):

  อัปโหลด / bulk / reprocess   OCR กินเวลาเป็นนาทีและต้องใช้ GPU · การอ่าน PDF
                               ใช้ poppler กับ libmagic ซึ่งเป็น system binary
                               · ไฟล์ต้นฉบับต้องอยู่บนดิสก์ที่ไม่หาย
                               ทั้งสามอย่างไม่มีบน serverless

ที่เหลือทำงานครบ: เข้าสู่ระบบ · ถาม-ตอบแบบสตรีม · ค้นคืน · ประวัติบทสนทนา ·
โควตา · analytics · จัดการผู้ใช้ · playground · health

ค่าที่ต้องตั้งบน Vercel (ดู README หัวข้อ "ขึ้น Vercel"):
  DATABASE_URL  REDIS_URL  APP_SECRET_KEY  LLM_BASE_URL  LLM_API_KEY
  LLM_MODEL  EMBEDDING_BASE_URL  EMBEDDING_API_KEY
  INGESTION_ENABLED=false  DB_POOL_ENABLED=false
  API_DOCS_ENABLED=false  COOKIE_SECURE=true
  TRUSTED_PROXY_HOPS=1  CORS_ALLOWED_ORIGINS=<โดเมนของ frontend>
  PYTHAINLP_DATA_DIR=/tmp/pythainlp  (ระบบไฟล์เขียนได้แค่ /tmp)

ถ้าเจอ FUNCTION_INVOCATION_FAILED: สาเหตุอยู่ใน log ของ function เสมอ
(`npx vercel logs <โดเมน>`) หน้าเว็บไม่แสดงให้ · README มีตารางเทียบอาการ
"""

import sys
from pathlib import Path

# แพ็กเกจ `app` อยู่ข้าง ๆ ไฟล์นี้ (api/app) แต่ Vercel ตั้ง cwd เป็นรากของ repo
# ไม่ใช่ api/ · ถ้าไม่เติมพาธนี้เข้าไป `import app.main` จะหาไม่เจอตอน deploy
# ทั้งที่รันในเครื่องได้ปกติ — เป็นความต่างที่ไปเจอตอน deploy แล้วไล่ยาก
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app.main import app  # noqa: E402

__all__ = ["app"]
