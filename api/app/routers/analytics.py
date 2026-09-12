"""Dashboard สำหรับ admin

คำถามที่ dashboard นี้ต้องตอบให้ได้ (PLAN.md ข้อ 14.2 ใช้ตัดสินว่าเมื่อไหร่ต้องขยายเครื่อง):
- คิว OCR รอนานแค่ไหน และ GPU ถูกใช้ไปเท่าไหร่
- user โดน 429 บ่อยแค่ไหน
- คำถามไหนที่คลังความรู้ยังตอบไม่ได้
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Float, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.deps import require_admin
from app.models.chat import ChatMessage, Feedback, MessageCitation
from app.models.document import Chunk, Document, IngestionJob
from app.models.quota import QuotaEvent, UsageCounter
from app.models.user import User

router = APIRouter(prefix="/api/admin", tags=["analytics"])


def _window_start(days: int) -> datetime:
    return datetime.now(settings.tz) - timedelta(days=days)


@router.get("/analytics/overview")
async def overview(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    since = _window_start(days)
    answers = ChatMessage.role == "assistant"

    totals = (
        await session.execute(
            select(
                func.count().label("total"),
                func.count().filter(~ChatMessage.answered_from_context).label("unanswered"),
                func.percentile_cont(0.5)
                .within_group(cast(ChatMessage.latency_ms, Float))
                .label("p50"),
                func.percentile_cont(0.95)
                .within_group(cast(ChatMessage.latency_ms, Float))
                .label("p95"),
            ).where(answers, ChatMessage.created_at >= since)
        )
    ).one()

    votes = (
        await session.execute(
            select(
                func.count().filter(Feedback.rating == 1).label("up"),
                func.count().filter(Feedback.rating == -1).label("down"),
            ).where(Feedback.created_at >= since)
        )
    ).one()

    # bucket ตามวันเวลาไทย ไม่ใช่ UTC ไม่งั้นกราฟจะเลื่อนไป 7 ชั่วโมง
    day = func.date(func.timezone(settings.quota_timezone, ChatMessage.created_at))
    daily_rows = (
        await session.execute(
            select(day.label("day"), func.count().label("messages"))
            .where(answers, ChatMessage.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
    ).all()

    total = totals.total or 0
    return {
        "window_days": days,
        "messages": total,
        "unanswered": totals.unanswered or 0,
        "unanswered_ratio": round((totals.unanswered or 0) / total, 3) if total else 0.0,
        "latency_ms": {
            "p50": round(totals.p50) if totals.p50 is not None else None,
            "p95": round(totals.p95) if totals.p95 is not None else None,
        },
        "feedback": {
            "up": votes.up or 0,
            "down": votes.down or 0,
            "negative_ratio": (
                round((votes.down or 0) / (votes.up + votes.down), 3)
                if (votes.up + votes.down)
                else 0.0
            ),
        },
        "daily": [{"day": str(row.day), "messages": row.messages} for row in daily_rows],
    }


@router.get("/analytics/unanswered")
async def unanswered_questions(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """คำถามที่ retrieval หา chunk ที่ผ่านเกณฑ์ไม่ได้ = ช่องว่างของคลังความรู้

    นี่คือรายการที่บอกว่าควรเอาเอกสารอะไรเข้าระบบเพิ่ม
    """
    since = _window_start(days)
    answer = ChatMessage.__table__.alias("answer")
    question = ChatMessage.__table__.alias("question")

    # หาข้อความ user ล่าสุดที่มาก่อนคำตอบใน session เดียวกัน
    # ทำได้เพราะ created_at ใช้ clock_timestamp() แล้ว (migration 0002)
    latest_question = (
        select(question.c.content)
        .where(
            question.c.session_id == answer.c.session_id,
            question.c.role == "user",
            question.c.created_at < answer.c.created_at,
        )
        .order_by(question.c.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    rows = (
        await session.execute(
            select(
                answer.c.id,
                answer.c.created_at,
                answer.c.session_id,
                latest_question.label("question"),
            )
            .where(~answer.c.answered_from_context, answer.c.created_at >= since)
            .order_by(answer.c.created_at.desc())
            .limit(limit)
        )
    ).all()

    return [
        {
            "message_id": str(row.id),
            "session_id": str(row.session_id),
            "question": row.question,
            "asked_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/analytics/documents")
async def cited_documents(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    since = _window_start(days)
    rows = (
        await session.execute(
            select(
                Document.id,
                Document.filename,
                func.count().label("citations"),
                func.avg(MessageCitation.score).label("avg_score"),
            )
            .select_from(MessageCitation)
            .join(Chunk, Chunk.id == MessageCitation.chunk_id)
            .join(Document, Document.id == Chunk.document_id)
            .join(ChatMessage, ChatMessage.id == MessageCitation.message_id)
            .where(ChatMessage.created_at >= since)
            .group_by(Document.id, Document.filename)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()

    return [
        {
            "document_id": str(row.id),
            "filename": row.filename,
            "citations": row.citations,
            "avg_score": round(float(row.avg_score), 4),
        }
        for row in rows
    ]


@router.get("/analytics/ingestion")
async def ingestion_stats(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """ตัวเลขที่ใช้ตัดสินว่าถึงเวลาขยายฮาร์ดแวร์หรือยัง"""
    since = _window_start(days)

    row = (
        await session.execute(
            select(
                func.count().label("jobs"),
                func.count().filter(IngestionJob.stage == "failed").label("failed"),
                func.count().filter(
                    IngestionJob.stage.not_in(("done", "failed"))
                ).label("in_flight"),
                func.coalesce(func.sum(IngestionJob.gpu_seconds), 0.0).label("gpu_seconds"),
                func.coalesce(func.sum(IngestionJob.pages_done), 0).label("pages"),
                func.percentile_cont(0.95)
                .within_group(
                    cast(
                        func.extract("epoch", IngestionJob.started_at - IngestionJob.queued_at),
                        Float,
                    )
                )
                .label("wait_p95"),
            ).where(IngestionJob.queued_at >= since)
        )
    ).one()

    pages = row.pages or 0
    gpu_seconds = float(row.gpu_seconds or 0.0)

    return {
        "window_days": days,
        "jobs": row.jobs or 0,
        "failed": row.failed or 0,
        "in_flight": row.in_flight or 0,
        "pages_processed": pages,
        "gpu_seconds": round(gpu_seconds, 1),
        # ค่านี้เอาไปแทนที่ OCR_SECONDS_PER_PAGE ใน .env เพื่อให้ ETA แม่นขึ้น
        "seconds_per_page": round(gpu_seconds / pages, 1) if pages else None,
        "queue_wait_p95_seconds": round(row.wait_p95) if row.wait_p95 is not None else None,
    }


@router.get("/quota/usage")
async def quota_usage(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    since = _window_start(days).date()

    rows = (
        await session.execute(
            select(
                User.id,
                User.email,
                User.role,
                func.coalesce(func.sum(UsageCounter.documents_used), 0).label("documents"),
                func.coalesce(func.sum(UsageCounter.pages_used), 0).label("pages"),
            )
            .select_from(User)
            .join(
                UsageCounter,
                and_(UsageCounter.user_id == User.id, UsageCounter.usage_date >= since),
                isouter=True,
            )
            .group_by(User.id, User.email, User.role)
            .order_by(func.coalesce(func.sum(UsageCounter.pages_used), 0).desc())
        )
    ).all()

    # ยิ่ง user โดนปฏิเสธบ่อย ยิ่งเป็นสัญญาณว่าโควตาตั้งต่ำไปหรือเครื่องเล็กไป
    blocked = (
        await session.execute(
            select(func.count())
            .select_from(QuotaEvent)
            .where(QuotaEvent.action == "release", QuotaEvent.created_at >= _window_start(days))
        )
    ).scalar_one()

    return {
        "window_days": days,
        "released_events": blocked,
        "users": [
            {
                "user_id": str(row.id),
                "email": row.email,
                "role": row.role,
                "documents": row.documents,
                "pages": row.pages,
                "unlimited": row.role == "admin" and settings.admin_unlimited,
            }
            for row in rows
        ],
    }
