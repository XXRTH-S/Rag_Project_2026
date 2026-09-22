"""หัวข้อของบทสนทนาต้องบอกได้ว่าคุยเรื่องอะไร

เดิมหัวข้อคือ "ข้อความแรกของผู้ใช้ ตัดที่ 80 ตัวอักษร" คำนวณใหม่ทุกครั้งที่โหลดหน้า
ผลที่เจอจริงในฐานข้อมูล (21 ก.ย. 2026): 201 จาก 366 บทสนทนามีหัวข้อว่า "hi"
แถบข้างจึงเป็นกำแพงคำเดียวกันซ้ำ ๆ ซึ่งเป็นสิ่งแรกที่คนเปิดหน้าแชทเห็น
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.orchestrator import TITLE_MAX_CHARS, derive_title
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from tests.conftest import TEST_PASSWORD


@pytest.mark.parametrize(
    "greeting", ["hi", "Hi", "  hello  ", "สวัสดี", "สวัสดีครับ", "ทดสอบ", "test", "ok"]
)
def test_greetings_do_not_become_a_title(greeting: str) -> None:
    """คำทักทายล้วนไม่บอกว่าคุยเรื่องอะไร ปล่อยให้คำถามถัดไปตั้งหัวข้อแทน"""
    assert derive_title(greeting) is None


@pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
def test_blank_questions_do_not_become_a_title(empty: str) -> None:
    assert derive_title(empty) is None


def test_a_real_question_becomes_the_title() -> None:
    assert derive_title("ลาพักร้อนได้ปีละกี่วัน") == "ลาพักร้อนได้ปีละกี่วัน"


def test_whitespace_is_collapsed() -> None:
    assert derive_title("ลาพักร้อน   ได้กี่วัน\n\nครับ") == "ลาพักร้อน ได้กี่วัน ครับ"


def test_long_questions_are_cut_on_a_word_boundary() -> None:
    """ภาษาไทยไม่มีช่องว่างคั่นคำ การตัดที่ตัวอักษรที่ N ตรง ๆ จะได้คำที่ขาดครึ่ง"""
    question = "พนักงานที่ทำงานครบหนึ่งปีแล้วต้องการลาพักร้อนสะสมข้ามปีจะต้องยื่นเรื่องกับใครและใช้เอกสารอะไรบ้างในการขออนุมัติจากผู้บังคับบัญชา"
    title = derive_title(question)

    assert title is not None
    assert len(title) <= TITLE_MAX_CHARS
    assert title.endswith("…")
    # ส่วนที่เหลือต้องเป็นคำขึ้นต้นของคำถามจริง ไม่ใช่ข้อความที่ถูกดัดแปลง
    assert question.startswith(title[:-1].rstrip())


async def test_the_title_is_stored_once_and_not_rewritten(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """คำถามแรกตั้งหัวข้อ คำถามต่อมาไม่เปลี่ยน

    หัวข้อที่เปลี่ยนไปมาทำให้คนหาบทสนทนาเก่าไม่เจอ — เขาจำจากหัวข้อแรกที่เห็น
    """
    await client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})

    first = await client.post("/api/chat", json={"message": "ลาพักร้อนได้ปีละกี่วัน"})
    assert first.status_code == 200
    session_id = first.text.split('"session_id": "')[1].split('"')[0]

    stored = await session.get(ChatSession, uuid.UUID(session_id))
    await session.refresh(stored)
    assert stored.title == "ลาพักร้อนได้ปีละกี่วัน"

    await client.post(
        "/api/chat", json={"message": "แล้วสะสมข้ามปีได้ไหม", "session_id": session_id}
    )
    await session.refresh(stored)
    assert stored.title == "ลาพักร้อนได้ปีละกี่วัน", "หัวข้อถูกเขียนทับด้วยคำถามที่สอง"


async def test_the_list_shows_the_stored_title(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    chat = ChatSession(user_id=user.id, channel="widget", title="เบิกค่าเดินทางอย่างไร")
    session.add(chat)
    await session.flush()
    session.add(ChatMessage(session_id=chat.id, role="user", content="hi"))
    await session.commit()

    await client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    body = (await client.get("/api/chat/sessions")).json()

    # หัวข้อต้องมาจากคอลัมน์ ไม่ใช่คำนวณใหม่จากข้อความแรก (ซึ่งคือ "hi")
    assert body["items"][0]["title"] == "เบิกค่าเดินทางอย่างไร"


async def test_a_session_without_a_title_still_shows_something(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """บทสนทนาที่มีแต่คำทักทายยังไม่มีหัวข้อโดยตั้งใจ ต้องไม่แสดงเป็นช่องว่าง"""
    chat = ChatSession(user_id=user.id, channel="widget", title=None)
    session.add(chat)
    await session.flush()
    session.add(ChatMessage(session_id=chat.id, role="user", content="hi"))
    await session.commit()

    await client.post("/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    body = (await client.get("/api/chat/sessions")).json()

    assert body["items"][0]["title"] == "บทสนทนาไม่มีหัวข้อ"
