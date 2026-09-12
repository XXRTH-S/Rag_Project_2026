"""ใช้ clock_timestamp() แทน now() ในตารางที่ต้องเรียงลำดับภายใน transaction เดียว

Revision ID: 0002
Revises: 0001

now() ของ PostgreSQL คืน "เวลาเริ่ม transaction" ไม่ใช่เวลาปัจจุบัน
แถวทุกแถวที่ insert ใน transaction เดียวกันจึงได้ created_at เท่ากันเป๊ะ

ผลกระทบจริง:
- chat_messages: ข้อความ user กับ assistant ถูกเขียนพร้อมกัน การเรียง
  ประวัติสนทนาด้วย created_at จึงไม่มีลำดับแน่นอน แล้ว LLM จะได้บทสนทนาที่สลับกัน
- quota_events: reserve กับ commit ที่เกิดใน transaction เดียวกันแยกลำดับไม่ออก
  ทำให้ audit trail อ่านไม่ได้

clock_timestamp() คืนเวลานาฬิกาจริงตอน insert แต่ละแถว จึงเรียงได้ถูกต้อง
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("chat_messages", "quota_events", "message_citations", "feedback")


def upgrade() -> None:
    for table in TABLES:
        if table == "message_citations":
            continue  # ไม่มีคอลัมน์ created_at
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT clock_timestamp()")


def downgrade() -> None:
    for table in TABLES:
        if table == "message_citations":
            continue
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT now()")
