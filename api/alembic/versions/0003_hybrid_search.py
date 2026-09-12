"""เพิ่มคอลัมน์สำหรับ keyword search ภาษาไทย

Revision ID: 0003
Revises: 0002

ทำไมต้องมีคอลัมน์แยก:
  Postgres ไม่มี parser สำหรับภาษาไทย `to_tsvector('simple', 'พนักงานลาพักร้อน')`
  จะได้ token เดียวคือทั้งประโยค ค้นหาอะไรไม่เจอเลย
  จึงต้อง tokenize ด้วย pythainlp ตอน ingest แล้วเก็บผลเป็นข้อความคั่นช่องว่าง
  ('พนักงาน ลา พักร้อน') ซึ่ง parser มาตรฐานตัดตามช่องว่างได้ถูกต้อง

search_vector เป็น generated column เพื่อให้ Postgres ดูแลความสอดคล้องเอง
ไม่ต้องกลัวลืมอัปเดตตอนแก้ search_text
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE chunks ADD COLUMN search_text TEXT")
    op.execute(
        """
        ALTER TABLE chunks ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED
        """
    )
    op.execute("CREATE INDEX ix_chunks_search_vector ON chunks USING gin (search_vector)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_search_vector")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS search_vector")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS search_text")
