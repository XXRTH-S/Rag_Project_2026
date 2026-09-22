"""เก็บหัวข้อของบทสนทนาไว้ในแถวของตัวเอง

Revision ID: 0005
Revises: 0004

ปัญหาที่แก้:
  แถบประวัติแชทคำนวณหัวข้อทุกครั้งที่โหลด ด้วยการหยิบข้อความแรกของผู้ใช้
  มาตัดที่ 80 ตัวอักษร ผลคือ:

    - ผู้ใช้ที่ทักว่า "hi" หรือ "ทดสอบ" ได้หัวข้อว่า "hi" ซึ่งไม่บอกอะไรเลย
      เมื่อมีหลายบทสนทนาแถบข้างกลายเป็นกำแพงคำเดียวกันซ้ำ ๆ
    - การตัดที่ตัวที่ 80 ตัดกลางคำไทย เพราะภาษาไทยไม่มีช่องว่างคั่นคำ
    - ต้องทำ DISTINCT ON ทุกครั้งที่เปิดหน้า ทั้งที่ค่าไม่เคยเปลี่ยน

วิธีแก้:
  เก็บ title ไว้ในแถวตอนที่บันทึกคำถามแรก คำนวณครั้งเดียวด้วยตัวตัดคำไทย
  (ดู app/llm/orchestrator.py) · เติมย้อนหลังให้แถวเดิมด้วยค่าที่ดีที่สุด
  เท่าที่ข้อมูลเก่ามี แล้วปล่อยให้แถวที่ไม่มีข้อความเลยเป็น NULL

  ไม่เรียก LLM มาสรุปหัวข้อโดยตั้งใจ — การ์ดใบเดียวโหลดโมเดลได้ทีละตัว
  การเพิ่มการเรียกต่อบทสนทนาใหม่ทุกครั้งแลกกับหัวข้อที่สวยขึ้นเล็กน้อย
  ไม่คุ้มกับคิวที่ยาวขึ้น
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_sessions ADD COLUMN title VARCHAR(120)")

    # เติมย้อนหลังจากคำถามแรกของผู้ใช้ในแต่ละบทสนทนา
    # ตัดที่ 120 ตัวอักษรตรง ๆ เพราะ SQL ไม่มีตัวตัดคำไทย — ของเก่าเอาเท่าที่ได้
    # บทสนทนาใหม่จะได้หัวข้อที่ตัดตามขอบคำจริงจากฝั่งแอป
    op.execute(
        """
        UPDATE chat_sessions s
        SET title = LEFT(BTRIM(m.content), 120)
        FROM (
            SELECT DISTINCT ON (session_id) session_id, content
            FROM chat_messages
            WHERE role = 'user'
            ORDER BY session_id, created_at
        ) m
        WHERE m.session_id = s.id AND BTRIM(m.content) <> ''
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chat_sessions DROP COLUMN title")
