import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.bootstrap import ensure_admin_user
from app.core.config import settings
from app.core.db import SessionLocal
from app.llm.warmup import schedule_warmup
from app.routers import (
    admin_documents,
    admin_users,
    analytics,
    auth,
    chat,
    chat_history,
    documents,
    health,
    playground,
    quota,
    widget,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """งานตอนเริ่มระบบ — ห้ามมีอะไรในนี้ทำให้ app ขึ้นไม่ได้

    ทุกอย่างที่นี่เป็นการ "เตรียมให้สะดวก" ไม่ใช่เงื่อนไขที่จำเป็นต่อการให้บริการ
    ถ้าอันไหนล้มก็ควรแค่บันทึกไว้แล้วเดินต่อ · บน serverless การล้มตรงนี้
    โผล่ออกไปเป็นแค่ FUNCTION_INVOCATION_FAILED ซึ่งไม่บอกอะไรเลย

    เจอจริงตอนขึ้น Vercel ครั้งแรก: mkdir ของ UPLOAD_DIR ล้มเพราะ
    ระบบไฟล์อ่านได้อย่างเดียว แล้วทั้ง API ขึ้นไม่ได้ทั้งที่ทุก endpoint
    ที่จะใช้จริงไม่ได้แตะดิสก์เลย
    """
    # สร้างพื้นที่อัปโหลดเฉพาะเมื่อเปิด ingestion
    if settings.ingestion_enabled:
        try:
            Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("สร้าง UPLOAD_DIR ไม่ได้: %s — การนำเข้าเอกสารจะใช้ไม่ได้", exc)

    log.info(
        "starting tier=%s llm=%s ocr=%s embed=%s ingestion=%s",
        settings.model_tier,
        settings.llm_model,
        settings.typhoon_ocr_model,
        settings.embedding_model,
        settings.ingestion_enabled,
    )

    # ให้ API เริ่มได้ก่อนรัน migration ในการติดตั้งครั้งแรก
    try:
        async with SessionLocal() as session:
            await ensure_admin_user(session)
    except Exception as exc:  # noqa: BLE001
        log.warning("ข้ามการสร้างบัญชี admin: %s — รัน alembic upgrade head แล้ว restart api", exc)

    # warmup เบื้องหลังเฉพาะโหมด ingestion เพื่อไม่เรียกซ้ำทุก serverless cold start
    if settings.ingestion_enabled:
        try:
            schedule_warmup()
        except Exception as exc:  # noqa: BLE001
            log.warning("ข้าม warmup: %s", exc)

    yield


# เปิดเอกสาร API ตาม API_DOCS_ENABLED; ไม่ผูกกับ tier ของโมเดล
_docs_enabled = settings.api_docs_enabled

app = FastAPI(
    title="RAG Workshop API",
    version="0.1.0",
    description="Retrieval + LLM orchestration + ingestion/OCR",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(quota.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(chat_history.router)
app.include_router(analytics.router)
app.include_router(playground.router)
app.include_router(widget.router)
app.include_router(admin_documents.router)
app.include_router(admin_users.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "rag-workshop-api", "docs": "/docs", "health": "/health/deep"}
