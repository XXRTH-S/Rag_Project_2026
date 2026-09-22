import asyncio
import logging
import uuid
from typing import Any

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.deps import get_optional_user
from app.llm import ollama_admin
from app.llm.client import ChatClient
from app.models.user import User

router = APIRouter(tags=["health"])
log = logging.getLogger("app.health")


def _opaque(name: str, exc: Exception) -> str:
    """แปลง exception เป็นรหัสอ้างอิง แทนการส่งข้อความดิบออกไป

    ข้อความ exception ของ asyncpg/httpx มีทั้งชื่อโฮสต์ พอร์ต และพาธไฟล์ในเครื่อง
    endpoint นี้ต้องเรียกได้โดยไม่ต้องล็อกอิน (monitor ภายนอกต้องใช้) การส่งข้อความ
    ดิบออกไปจึงเท่ากับแจกผังระบบให้คนนอก

    ใช้วิธีเดียวกับ /api/chat — log ตัวเต็มไว้ข้างในพร้อมรหัส แล้วส่งออกแค่รหัสนั้น
    """
    reference = uuid.uuid4().hex[:8]
    log.warning("health check ล้มเหลว name=%s ref=%s", name, reference, exc_info=exc)
    return f"ตรวจไม่ผ่าน (รหัสอ้างอิง {reference})"


@router.get("/health")
async def health() -> dict[str, str]:
    """liveness — ตอบเร็ว ไม่แตะ dependency ใด ๆ"""
    return {"status": "ok"}


async def _check_postgres(session: AsyncSession) -> dict[str, Any]:
    try:
        await session.execute(text("SELECT 1"))
        ext = await session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        version = ext.scalar_one_or_none()
        if version is None:
            return {"ok": False, "detail": "ยังไม่ได้เปิด extension vector — รัน alembic upgrade head"}
        return {"ok": True, "pgvector": version}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": _opaque("postgres", exc)}


async def _check_redis() -> dict[str, Any]:
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.ping()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": _opaque("redis", exc)}
    finally:
        await client.aclose()


def _has_model(wanted: str, available: list[str]) -> bool:
    """Ollama คืนชื่อพร้อม tag เสมอ (`typhoon-ocr:latest`) แต่ใน .env มักเขียนสั้น ๆ
    ถ้าเทียบตรงตัวจะรายงานว่าโมเดลยังไม่พร้อมทั้งที่ pull มาแล้ว"""
    candidates = {wanted, f"{wanted}:latest"} if ":" not in wanted else {wanted}
    return any(model in candidates or model.split(":")[0] == wanted for model in available)


async def _probe_provider(name: str, client: ChatClient) -> dict[str, Any]:
    try:
        models = await client.list_models()
    except httpx.HTTPError as exc:
        return {"name": name, "ok": False, "model": client.model, "detail": _opaque(f"llm:{name}", exc)}

    ok = _has_model(client.model, models)
    return {
        "name": name,
        "ok": ok,
        "model": client.model,
        "detail": None if ok else f"ยังไม่ได้ pull โมเดล {client.model}",
    }


async def _check_llm() -> dict[str, Any]:
    """ตรวจทุก provider ที่ตั้งไว้ — ระบบยังใช้ได้ถ้ามีตัวใดตัวหนึ่งพร้อม"""
    from app.llm.chain import providers

    configured = providers()
    results = await asyncio.gather(
        *(_probe_provider(p.name, p.client) for p in configured)
    )

    usable = [r for r in results if r["ok"]]
    detail = None
    if not usable:
        detail = " · ".join(f"{r['name']}: {r['detail']}" for r in results) or "ไม่ได้ตั้งค่า provider"

    return {
        "ok": bool(usable),
        "configured_model": settings.llm_model,
        "providers": results,
        # ตัวที่จะถูกใช้จริงเมื่อมีคำถามเข้ามาตอนนี้
        "active": usable[0]["name"] if usable else None,
        "detail": detail,
    }


async def _check_ocr() -> dict[str, Any]:
    try:
        models = await ChatClient(
            base_url=settings.typhoon_ocr_base_url,
            api_key=settings.typhoon_ocr_api_key,
            model=settings.typhoon_ocr_model,
        ).list_models()
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": _opaque("ocr", exc)}
    wanted = settings.typhoon_ocr_model
    ok = _has_model(wanted, models)
    return {
        "ok": ok,
        "configured_model": wanted,
        "detail": None if ok else f"ยังไม่ได้ pull โมเดล {wanted}",
    }


async def _check_embeddings() -> dict[str, Any]:
    # ยิงเองแทนการเรียก EmbeddingClient.health() เพื่อให้รายงานสาเหตุจริงได้
    # health check ที่กลืน exception ทิ้งแล้วบอกแค่ "ไม่พร้อม" ทำให้ debug ไม่ได้
    base = settings.embedding_base_url.rstrip("/")
    detail: str | None = None
    ok = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base}/health")
            ok = resp.status_code == 200
            if not ok:
                detail = f"{base}/health ตอบ {resp.status_code}"
    except httpx.HTTPError as exc:
        detail = _opaque("embeddings", exc)

    if not ok and detail is None:
        detail = "TEI ยังไม่พร้อม (ครั้งแรกต้องโหลดโมเดลก่อน ใช้เวลาหลายนาที)"

    return {
        "ok": ok,
        "model": settings.embedding_model,
        "dim": settings.embedding_dim,
        "detail": detail,
    }


DEEP_CHECK_BUDGET_SECONDS = 20


async def _guarded(name: str, coro) -> dict[str, Any]:
    """ไม่ให้ dependency ตัวเดียวที่ค้างลากทั้ง endpoint ไปด้วย"""
    try:
        async with asyncio.timeout(DEEP_CHECK_BUDGET_SECONDS):
            return await coro
    except TimeoutError:
        return {"ok": False, "detail": f"{name} ไม่ตอบใน {DEEP_CHECK_BUDGET_SECONDS} วินาที"}


def _summarised(checks: dict[str, Any]) -> dict[str, Any]:
    """เหลือแค่ผ่าน/ไม่ผ่าน สำหรับผู้เรียกที่ไม่ใช่ admin

    รายละเอียดที่ตัดออกคือของที่มีประโยชน์กับคนที่จะลองโจมตีล้วน ๆ —
    รุ่น pgvector, ชื่อโมเดลที่ใช้, รายชื่อ provider, ว่าตัวไหนกำลังทำงานอยู่
    และสถานะ GPU · ส่วนที่เหลือไว้พอให้ monitor ภายนอกดูเขียว/แดงได้ตามเดิม
    """
    return {name: {"ok": bool(check["ok"])} for name, check in checks.items()}


@router.get("/health/deep")
async def health_deep(
    session: AsyncSession = Depends(get_session),
    viewer: User | None = Depends(get_optional_user),
) -> JSONResponse:
    """readiness — เช็คทุก dependency ใช้ยืนยันเฟส 0

    ตอบได้โดยไม่ต้องล็อกอิน เพราะ monitor ภายนอกและ `check.ps1` ต้องเรียกได้
    แต่ตอบ *ไม่เท่ากัน*: รายละเอียดทั้งหมดเห็นเฉพาะ admin
    """
    # เช็ค DB ให้จบก่อน ไม่เอาไปรวมใน gather กับ network check ที่ช้า
    # ถ้า client ตัดการเชื่อมต่อระหว่างรอ network session จะถูกปิดขณะ query ยังทำงาน
    # แล้วได้ IllegalStateChangeError ซึ่งทำให้ health check เองกลายเป็น 500
    postgres = await _check_postgres(session)

    redis_status, llm, ocr, embeddings, gpu_models = await asyncio.gather(
        _guarded("redis", _check_redis()),
        _guarded("llm", _check_llm()),
        _guarded("ocr", _check_ocr()),
        _guarded("embeddings", _check_embeddings()),
        ollama_admin.loaded_models_safe(),
    )

    checks = {
        "postgres": postgres,
        "redis": redis_status,
        "llm": llm,
        "ocr": ocr,
        "embeddings": embeddings,
    }
    all_ok = all(c["ok"] for c in checks.values())
    status_code = 200 if all_ok else 503

    if viewer is None or not viewer.is_admin:
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if all_ok else "degraded",
                "checks": _summarised(checks),
            },
        )

    gpu: dict[str, Any] = {"loaded_models": ollama_admin.summarize(gpu_models)}
    # ต้องเป็น "100% GPU" — ถ้าไม่ใช่ OCR จะช้ากว่าปกติหลายเท่าแบบไม่มี error
    warning = ollama_admin.spill_warning(gpu_models)
    if warning:
        gpu["warning"] = warning

    body: dict[str, Any] = {
        "status": "ok" if all_ok else "degraded",
        "tier": settings.model_tier,
        "checks": checks,
        "gpu": gpu,
    }
    return JSONResponse(status_code=status_code, content=body)
