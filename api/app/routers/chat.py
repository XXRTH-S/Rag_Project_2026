import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.core.db import get_session
from app.core.deps import get_current_user
from app.llm import orchestrator
from app.models.chat import ChatMessage, Feedback
from app.models.user import User

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID | None = None
    collection: str | None = None


class FeedbackRequest(BaseModel):
    message_id: uuid.UUID
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=2000)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    # แชทไม่กินโควตารายวัน แต่กิน GPU ทุกครั้ง — บนการ์ดใบเดียวที่ตอบได้ทีละคำขอ
    # การยิงรัวทำให้คนอื่นรอทั้งคิว จึงต้องคุมความถี่แยกจากโควตา
    await ratelimit.enforce(
        request,
        scope="chat",
        limit=settings.rate_limit_chat_per_minute,
        window_seconds=60,
    )

    chat_session = await orchestrator.ensure_session(
        session,
        payload.session_id,
        channel="widget",
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        client_ip=request.client.host if request.client else None,
    )
    await session.commit()

    # admin เห็นทุกเอกสาร ส่วน user เห็นเฉพาะของตัวเอง — กรองที่ระดับ SQL
    owner_id = None if user.is_admin else user.id

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("session", {"session_id": str(chat_session.id)})
        try:
            async for event, data in orchestrator.stream_answer(
                session,
                chat_session,
                payload.message,
                owner_id=owner_id,
                collection=payload.collection,
            ):
                yield _sse(event, data)
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"detail": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # กัน nginx/proxy บางตัว buffer จนสตรีมมาเป็นก้อนเดียวตอนจบ
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feedback(
    payload: FeedbackRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    if payload.rating == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "rating ต้องเป็น 1 หรือ -1")

    message = await session.get(ChatMessage, payload.message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบข้อความ")

    session.add(
        Feedback(message_id=payload.message_id, rating=payload.rating, comment=payload.comment)
    )
    await session.commit()
