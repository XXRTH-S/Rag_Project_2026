"""อ่านประวัติบทสนทนากลับมา

ทำไมต้องมี: ทุกคำถาม-คำตอบถูกเขียนลง chat_sessions / chat_messages อยู่แล้ว
แต่เดิมไม่มีทางอ่านกลับ — refresh หน้าแชทแล้วบทสนทนาหายทั้งที่ข้อมูลยังอยู่ใน DB

ขอบเขตการมองเห็น: ผู้ใช้เห็นเฉพาะ session ของตัวเอง admin ก็เช่นกัน
ไม่ใช่เพราะ admin ไม่มีสิทธิ์ แต่เพราะบทสนทนาของคนอื่นเป็นเรื่องส่วนตัว
และ analytics มีตัวเลขรวมให้อยู่แล้วโดยไม่ต้องอ่านข้อความของใคร
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_user
from app.models.chat import ChatMessage, ChatSession, Feedback, MessageCitation
from app.models.user import User

router = APIRouter(prefix="/api/chat", tags=["chat-history"])

# ตัดหัวข้อให้พอเห็นว่าคุยเรื่องอะไร ยาวกว่านี้ก็ล้นแถบข้างอยู่ดี
TITLE_MAX_CHARS = 80


class SessionSummary(BaseModel):
    id: uuid.UUID
    title: str
    message_count: int
    last_message_at: str
    created_at: str


class Citation(BaseModel):
    rank: int
    document_id: uuid.UUID | None
    document_name: str | None
    page_no: int | None
    score: float


class HistoryMessage(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: str
    answered_from_context: bool
    citations: list[Citation]
    feedback: int | None


class SessionDetail(BaseModel):
    id: uuid.UUID
    created_at: str
    messages: list[HistoryMessage]


async def _owned_session(
    session_id: uuid.UUID, user: User, session: AsyncSession
) -> ChatSession:
    """ดึง session ที่เป็นของผู้ใช้คนนี้จริง

    ตอบ 404 ไม่ใช่ 403 เมื่อเป็นของคนอื่น เพราะ 403 เท่ากับยืนยันว่า id นี้มีจริง
    ซึ่งทำให้เดา id ของคนอื่นได้ว่ามีอยู่หรือไม่
    """
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None or chat_session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบบทสนทนา")
    return chat_session


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SessionSummary]:
    # นับข้อความและหาเวลาล่าสุดในคิวรี่เดียว ไม่วนถามทีละ session
    stats = (
        select(
            ChatMessage.session_id.label("sid"),
            func.count().label("n"),
            func.max(ChatMessage.created_at).label("last_at"),
        )
        .group_by(ChatMessage.session_id)
        .subquery()
    )

    # join ธรรมดา (ไม่ใช่ outer) เพื่อตัด session ที่ยังไม่มีข้อความเลยออกไป
    # แถวแบบนั้นเกิดได้จริง: POST /chat สร้าง session ก่อนเรียกโมเดล
    # ถ้าโมเดลล้มกลางทาง session เปล่าจะค้างอยู่ ซึ่งไม่ควรโชว์ให้ผู้ใช้เห็น
    rows = (
        await session.execute(
            select(ChatSession, stats.c.n, stats.c.last_at)
            .join(stats, stats.c.sid == ChatSession.id)
            .where(ChatSession.user_id == user.id)
            .order_by(stats.c.last_at.desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    ids = [row[0].id for row in rows]

    # หัวข้อ = คำถามแรกของผู้ใช้ใน session นั้น · DISTINCT ON เป็นของ Postgres
    # ได้แถวแรกต่อ session ในคิวรี่เดียว ไม่ต้องยิงทีละอัน
    first_q = (
        await session.execute(
            select(ChatMessage.session_id, ChatMessage.content)
            .where(ChatMessage.session_id.in_(ids), ChatMessage.role == "user")
            .order_by(ChatMessage.session_id, ChatMessage.created_at)
            .distinct(ChatMessage.session_id)
        )
    ).all()
    titles = {sid: content for sid, content in first_q}

    out = []
    for chat_session, count, last_at in rows:
        raw = (titles.get(chat_session.id) or "").strip()
        title = raw[:TITLE_MAX_CHARS] + "…" if len(raw) > TITLE_MAX_CHARS else raw
        out.append(
            SessionSummary(
                id=chat_session.id,
                title=title or "บทสนทนาไม่มีหัวข้อ",
                message_count=count,
                last_message_at=last_at.isoformat(),
                created_at=chat_session.created_at.isoformat(),
            )
        )
    return out


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session_detail(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionDetail:
    chat_session = await _owned_session(session_id, user, session)

    messages = (
        (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at, ChatMessage.role.desc())
            )
        )
        .scalars()
        .all()
    )
    if not messages:
        return SessionDetail(
            id=chat_session.id, created_at=chat_session.created_at.isoformat(), messages=[]
        )

    message_ids = [m.id for m in messages]

    cites: dict[uuid.UUID, list[Citation]] = {}
    for row in (
        (
            await session.execute(
                select(MessageCitation)
                .where(MessageCitation.message_id.in_(message_ids))
                .order_by(MessageCitation.rank)
            )
        )
        .scalars()
        .all()
    ):
        cites.setdefault(row.message_id, []).append(
            Citation(
                rank=row.rank,
                document_id=row.document_id,
                document_name=row.document_name,
                page_no=row.page_no,
                score=row.score,
            )
        )

    # ให้คะแนนซ้ำได้หลายครั้ง ครั้งล่าสุดถือเป็นคำตัดสิน — ตรงกับที่ผู้ใช้เข้าใจ
    # ว่ากดใหม่แล้วทับของเก่า (ตาราง feedback ไม่ได้บังคับ unique ต่อข้อความ)
    ratings: dict[uuid.UUID, int] = {}
    for mid, rating in (
        await session.execute(
            select(Feedback.message_id, Feedback.rating)
            .where(Feedback.message_id.in_(message_ids))
            .order_by(Feedback.created_at)
        )
    ).all():
        ratings[mid] = rating

    return SessionDetail(
        id=chat_session.id,
        created_at=chat_session.created_at.isoformat(),
        messages=[
            HistoryMessage(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at.isoformat(),
                answered_from_context=m.answered_from_context,
                citations=cites.get(m.id, []),
                feedback=ratings.get(m.id),
            )
            for m in messages
        ],
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await _owned_session(session_id, user, session)
    # chat_messages และ message_citations ผูก CASCADE กับ session อยู่แล้ว
    await session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await session.commit()
