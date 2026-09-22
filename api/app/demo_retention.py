"""Expiry applies only to the five deterministic demo IDs, never existing real users."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.demo import demo_id
from app.models.chat import ChatMessage, ChatSession, MessageCitation
from app.models.document import Document, IngestionJob
from app.models.quota import QuotaEvent, UsageCounter


async def expire_demo(session: AsyncSession, *, apply: bool = False, now: datetime | None = None):
    cutoff = (now or datetime.now(UTC)) - timedelta(days=90)
    owners = [demo_id(i) for i in range(1, 6)]
    await session.execute(text("SELECT pg_advisory_xact_lock(2026091301)"))
    active = exists(
        select(IngestionJob.id).where(
            IngestionJob.document_id == Document.id, IngestionJob.stage.notin_(["done", "failed"])
        )
    )
    docs = (
        (
            await session.execute(
                select(Document)
                .where(
                    Document.owner_id.in_(owners),
                    Document.created_at < cutoff,
                    Document.status.in_(["ready", "failed"]),
                    ~active,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    sessions = select(ChatSession.id).where(ChatSession.user_id.in_(owners))
    old_messages = (
        (
            await session.execute(
                select(ChatMessage.id).where(
                    ChatMessage.session_id.in_(sessions), ChatMessage.created_at < cutoff
                )
            )
        )
        .scalars()
        .all()
    )
    report = {
        "expired_documents": len(docs),
        "expired_messages": len(old_messages),
        "applied": apply,
    }
    if not apply:
        await session.rollback()
        return report
    for doc in docs:
        root = Path(settings.upload_dir).resolve()
        path = Path(doc.storage_path).resolve()
        if not path.is_relative_to(root / str(doc.owner_id)):
            raise ValueError("Refusing to remove a file outside its demo owner directory")
        # Keep DB row when file deletion fails so the next run can retry.
        path.unlink(missing_ok=True)
        cited_messages = select(MessageCitation.message_id).where(
            MessageCitation.document_id == doc.id
        )
        await session.execute(delete(ChatMessage).where(ChatMessage.id.in_(cited_messages)))
        await session.delete(doc)
    if old_messages:
        await session.execute(delete(ChatMessage).where(ChatMessage.id.in_(old_messages)))
    await session.flush()
    await session.execute(
        delete(ChatSession).where(
            ChatSession.user_id.in_(owners),
            ~exists(select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id)),
        )
    )
    await session.execute(
        delete(QuotaEvent).where(QuotaEvent.user_id.in_(owners), QuotaEvent.created_at < cutoff)
    )
    await session.execute(
        delete(UsageCounter).where(
            UsageCounter.user_id.in_(owners), UsageCounter.usage_date < cutoff.date()
        )
    )
    await session.commit()
    return report
