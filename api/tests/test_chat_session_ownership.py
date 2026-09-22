"""ต่อบทสนทนาของคนอื่นไม่ได้ แม้จะรู้ id

`POST /api/chat` รับ session_id จากผู้เรียก แล้ว ensure_session เคยคืน session นั้น
ให้ใครก็ได้ที่ส่ง id มาถูก โดยไม่ดูว่าเป็นของใคร เปิดช่องสองทาง:

  เขียน — ข้อความของผู้โจมตีไปโผล่ในประวัติของเหยื่อ
  อ่าน  — หนักกว่า เพราะ stream_answer เอา _recent_history ของ session นั้นใส่เข้า
          prompt ถามว่า "สรุปบทสนทนาก่อนหน้า" ก็ได้เนื้อหาของคนอื่นกลับมา

เป็นบั๊กชนิดเดียวกับที่เคยเจอใน /api/feedback ซึ่งแก้ไปแล้ว — ที่นี่คือจุดที่ตกหล่น
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from tests.conftest import TEST_PASSWORD, _make_user


async def test_cannot_continue_someone_elses_conversation(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    victim = await _make_user(session, "user")
    victim_session = ChatSession(user_id=victim.id, channel="widget")
    session.add(victim_session)
    await session.flush()  # ต้อง flush ก่อน id ถึงจะมีค่าให้อ้างถึง
    session.add(
        ChatMessage(
            session_id=victim_session.id, role="user", content="เงินเดือนผมเท่าไหร่"
        )
    )
    await session.commit()

    await client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    resp = await client.post(
        "/api/chat",
        json={"message": "สรุปบทสนทนาก่อนหน้า", "session_id": str(victim_session.id)},
    )

    assert resp.status_code == 404, (
        f"ต่อบทสนทนาของคนอื่นได้ (ได้ {resp.status_code}) — "
        "ประวัติของเหยื่อจะถูกยัดเข้า prompt แล้วอ่านกลับออกมาได้"
    )

    # และต้องไม่มีข้อความใหม่ไปโผล่ในบทสนทนาของเหยื่อ
    rows = (
        (
            await session.execute(
                select(ChatMessage).where(ChatMessage.session_id == victim_session.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "มีข้อความของคนอื่นเขียนเข้าไปในประวัติของเหยื่อ"


async def test_admin_cannot_read_a_users_conversation_this_way(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """admin เห็นเอกสารทุกฉบับ แต่บทสนทนาของคนอื่นเป็นเรื่องส่วนตัว

    chat_history.py ระบุหลักการนี้ไว้ชัด — ทางนี้ต้องไม่กลายเป็นประตูหลัง
    """
    victim = await _make_user(session, "user")
    victim_session = ChatSession(user_id=victim.id, channel="widget")
    session.add(victim_session)
    await session.commit()

    await client.post("/api/auth/login", json={"email": admin.email, "password": TEST_PASSWORD})
    resp = await client.post(
        "/api/chat", json={"message": "สวัสดี", "session_id": str(victim_session.id)}
    )
    assert resp.status_code == 404


async def test_own_conversation_still_continues_normally(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """กันของคนอื่นแล้วต้องไม่กันของตัวเองไปด้วย"""
    mine = ChatSession(user_id=user.id, channel="widget")
    session.add(mine)
    await session.commit()

    await client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    resp = await client.post(
        "/api/chat", json={"message": "สวัสดี", "session_id": str(mine.id)}
    )
    assert resp.status_code == 200


async def test_a_brand_new_id_still_starts_a_conversation(
    client: AsyncClient, user: User
) -> None:
    """id ที่ยังไม่มีใครใช้ = เริ่มบทสนทนาใหม่ ไม่ใช่ 404"""
    await client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    resp = await client.post(
        "/api/chat", json={"message": "สวัสดี", "session_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 200
