"""ลบบทสนทนาเก่าทิ้ง — ดูก่อนเป็นค่าเริ่มต้น ต้องใส่ --apply ถึงจะลบจริง

ทำไมต้องมี: การทดสอบระบบทิ้งบทสนทนาสั้น ๆ ไว้เยอะมาก (ตรวจเมื่อ 21 ก.ย. 2026
เจอ 366 บทสนทนา / 768 ข้อความ แทบทั้งหมดคือ "hi" สองข้อความ) แถบประวัติจึงเป็น
กำแพงคำเดียวกันซ้ำ ๆ ซึ่งเป็นสิ่งแรกที่คนเปิดหน้าแชทเห็น

ตัวอย่าง

    # ดูว่าจะลบอะไรบ้าง ไม่แตะข้อมูล
    python scripts/purge_chats.py --owner admin@example.com --before 2026-09-20

    # ลบจริง
    python scripts/purge_chats.py --owner admin@example.com --before 2026-09-20 --apply

    # เก็บกวาดบทสนทนาที่ไม่มีข้อความเลย (เกิดเมื่อโมเดลล้มก่อนตอบ)
    python scripts/purge_chats.py --empty-only --apply

    # ลบเฉพาะที่เป็นการลองระบบ — ทักทายล้วนและไม่ได้คุยต่อ
    python scripts/purge_chats.py --owner admin@example.com --greetings-only --apply

ข้อบังคับที่ตั้งใจให้ใช้ยากขึ้น:
  - ต้องระบุ --owner กับ --before เสมอ ยกเว้นโหมด --empty-only
    ไม่มีค่าเริ่มต้นที่ลบเป็นวงกว้าง เพราะสคริปต์ลบข้อมูลที่พลาดแล้วไม่มีทางกลับ
  - บัญชีสาธิต demo01-demo05 ถูกกันไว้เสมอ เป็นข้อมูลที่ตั้งใจให้มี
    ถ้าต้องการล้างของบัญชีสาธิตให้ใช้ scripts/retention_demo.py ซึ่งทำเรื่องนั้นโดยเฉพาะ
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, engine
from app.demo import demo_id
from app.llm.orchestrator import _GREETINGS
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User

# ล็อกตัวเดียวกับ retention_demo.py — ห้ามสองสคริปต์ลบพร้อมกัน
ADVISORY_LOCK = 2026091301

# ใช้รายการเดียวกับที่ orchestrator ใช้ตัดสินว่าจะตั้งหัวข้อไหม
# ถ้าแยกกันสองที่ เพิ่มคำใหม่ที่หนึ่งแล้วลืมอีกที่ พฤติกรรมจะไม่ตรงกันเงียบ ๆ
# บวก "" เพราะหัวข้อว่างคือบทสนทนาที่ derive_title ปฏิเสธไปแล้ว
GREETINGS = _GREETINGS | {""}


async def purge(
    session: AsyncSession,
    *,
    owner_email: str | None,
    before: datetime | None,
    empty_only: bool,
    greetings_only: bool,
    apply: bool,
) -> dict:
    await session.execute(text(f"SELECT pg_advisory_xact_lock({ADVISORY_LOCK})"))

    protected = [demo_id(i) for i in range(1, 6)]
    has_no_messages = ~exists(
        select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id)
    )

    target = select(ChatSession.id).where(ChatSession.user_id.notin_(protected))

    if empty_only:
        # บทสนทนาที่ไม่มีข้อความเลยไม่มีอะไรให้เสีย แต่กันของวันนี้ไว้
        # เผื่อมีอันที่เพิ่งสร้างและกำลังรอคำตอบอยู่
        target = target.where(has_no_messages, ChatSession.created_at < before)
    else:
        owner = (
            await session.execute(select(User).where(User.email == owner_email.lower()))
        ).scalar_one_or_none()
        if owner is None:
            raise SystemExit(f"ไม่พบบัญชี {owner_email}")
        if owner.id in protected:
            raise SystemExit("บัญชีสาธิตต้องใช้ scripts/retention_demo.py")
        target = target.where(ChatSession.user_id == owner.id, ChatSession.created_at < before)

        if greetings_only:
            # เงื่อนไขของ "การลองระบบ": หัวข้อเป็นคำทักทายล้วน (หรือยังตั้งไม่ได้)
            # *และ* ไม่ได้คุยต่อเกินหนึ่งรอบ · ต้องครบทั้งสองข้อ
            #
            # ข้อหลังสำคัญ: คนที่ทักว่า "สวัสดี" ก่อนแล้วถามคำถามจริงต่อ
            # มีบทสนทนาที่ควรเก็บไว้ การดูแค่หัวข้ออย่างเดียวจะลบของเขาทิ้ง
            message_count = (
                select(func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.session_id == ChatSession.id)
                .scalar_subquery()
            )
            greeting_title = func.btrim(func.lower(func.coalesce(ChatSession.title, ""))).in_(
                sorted(GREETINGS)
            )
            target = target.where(greeting_title, message_count <= 2)

    ids = (await session.execute(target)).scalars().all()
    messages = (
        await session.execute(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id.in_(ids))
        )
    ).scalar_one() if ids else 0

    mode = "empty-only" if empty_only else f"{owner_email}{' (ทักทายล้วน)' if greetings_only else ''}"
    report = {
        "sessions": len(ids),
        "messages": int(messages),
        "applied": apply,
        "mode": mode,
    }
    if not apply or not ids:
        await session.rollback()
        return report

    # chat_messages และ message_citations ผูก CASCADE กับ session อยู่แล้ว
    await session.execute(delete(ChatSession).where(ChatSession.id.in_(ids)))
    await session.commit()
    return report


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--owner", help="อีเมลของเจ้าของบทสนทนาที่จะลบ")
    parser.add_argument("--before", help="ลบเฉพาะที่สร้างก่อนวันนี้ (YYYY-MM-DD)")
    parser.add_argument(
        "--empty-only",
        action="store_true",
        help="ลบเฉพาะบทสนทนาที่ไม่มีข้อความเลย ทุกเจ้าของ (ยกเว้นบัญชีสาธิต)",
    )
    parser.add_argument(
        "--greetings-only",
        action="store_true",
        help="ลบเฉพาะที่ทักทายล้วนและไม่ได้คุยต่อ — การลองระบบ ไม่ใช่บทสนทนาจริง",
    )
    parser.add_argument("--apply", action="store_true", help="ลบจริง ไม่ใส่ = แค่ดู")
    args = parser.parse_args()

    if args.empty_only:
        if args.owner or args.greetings_only:
            parser.error("--empty-only ใช้ร่วมกับตัวเลือกอื่นไม่ได้")
        # ค่าเริ่มต้นที่ปลอดภัย: ไม่แตะของที่สร้างวันนี้
        cutoff = datetime.fromisoformat(args.before) if args.before else datetime.now(UTC)
    else:
        if not args.owner:
            parser.error("ต้องระบุ --owner (หรือใช้ --empty-only)")
        # --greetings-only แคบพออยู่แล้ว ไม่บังคับ --before · ค่าเริ่มต้นคือทุกอย่างจนถึงตอนนี้
        if not args.before and not args.greetings_only:
            parser.error("ต้องระบุ --before (หรือใช้ --greetings-only)")
        cutoff = datetime.fromisoformat(args.before) if args.before else datetime.now(UTC)

    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)

    try:
        async with SessionLocal() as session:
            report = await purge(
                session,
                owner_email=args.owner,
                before=cutoff,
                empty_only=args.empty_only,
                greetings_only=args.greetings_only,
                apply=args.apply,
            )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if not args.apply:
            print("ยังไม่ได้ลบอะไร — ใส่ --apply เพื่อลบจริง", flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
