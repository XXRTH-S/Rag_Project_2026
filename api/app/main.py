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
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    log.info(
        "starting tier=%s llm=%s ocr=%s embed=%s",
        settings.model_tier,
        settings.llm_model,
        settings.typhoon_ocr_model,
        settings.embedding_model,
    )

    # ห้ามล้มทั้ง app ถ้าตารางยังไม่ถูกสร้าง — ตอน setup ครั้งแรก api ต้องขึ้นมาให้ได้
    # ก่อน แล้วค่อยรัน `alembic upgrade head` ผ่าน exec
    try:
        async with SessionLocal() as session:
            await ensure_admin_user(session)
    except Exception as exc:  # noqa: BLE001
        log.warning("ข้ามการสร้างบัญชี admin: %s — รัน alembic upgrade head แล้ว restart api", exc)

    # โหลดโมเดลเข้า VRAM เบื้องหลัง ไม่ให้คำถามแรกต้องรอ 21 วินาที
    schedule_warmup()

    yield


# /docs กับ /openapi.json เปิดสาธารณะตามค่าเริ่มต้นของ FastAPI ซึ่งเท่ากับแจกผัง
# ของทั้ง API ให้คนที่ยังไม่ได้ล็อกอิน รวมถึงชื่อ endpoint ฝั่ง admin และรูปร่าง payload
# ทั้งหมด — เป็นแผนที่ชั้นดีให้คนที่จะลองโจมตี
#
# ยังเปิดไว้ตอน dev เพราะจำเป็นกับการต่อ frontend แต่ต้องปิดเมื่อขึ้นใช้จริง
# คุมด้วย API_DOCS_ENABLED ใน .env ไม่ผูกกับ tier เพราะ tier บอกเรื่องโมเดล ไม่ใช่เรื่องความปลอดภัย
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
