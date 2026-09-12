"""กันไม่ให้ created_at กลับไปใช้ now()

PostgreSQL now() คืน "เวลาเริ่ม transaction" ไม่ใช่เวลาปัจจุบัน แถวทุกแถวที่เขียน
ใน transaction เดียวกันจึงได้เวลาเท่ากันเป๊ะ แล้วเรียงลำดับไม่ได้

ผลกระทบจริงคือประวัติสนทนาที่ส่งเข้า LLM อาจสลับ user กับ assistant
ซึ่งทำให้โมเดลเข้าใจบริบทผิดโดยไม่มีอะไรฟ้อง
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.user import User


async def test_messages_written_in_one_transaction_get_distinct_timestamps(
    session: AsyncSession, user: User
) -> None:
    chat_session = ChatSession(id=uuid.uuid4(), channel="widget", user_id=user.id)
    session.add(chat_session)
    await session.flush()

    session.add(ChatMessage(session_id=chat_session.id, role="user", content="คำถาม"))
    await session.flush()
    session.add(ChatMessage(session_id=chat_session.id, role="assistant", content="คำตอบ"))
    await session.commit()

    rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_session.id)
            .order_by(ChatMessage.created_at)
        )
    ).scalars().all()

    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].created_at < rows[1].created_at, (
        "created_at ซ้ำกัน — แปลว่า default กลับไปเป็น now() แล้ว การเรียงประวัติสนทนาจะพัง"
    )
