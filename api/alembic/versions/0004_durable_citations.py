"""ทำให้การอ้างอิงในประวัติแชทอยู่รอดเมื่อ chunk ถูกลบ

Revision ID: 0004
Revises: 0003

ปัญหาที่แก้:
  message_citations.chunk_id เดิมเป็น NOT NULL + ON DELETE CASCADE ไปที่ chunks
  แต่ chunk ถูกลบเป็นเรื่องปกติ ไม่ใช่กรณียกเว้น — ทั้งการลบเอกสารและการสั่ง
  reprocess (ซึ่ง DELETE chunk เก่าทั้งหมดก่อนสร้างใหม่) ทำให้แถวอ้างอิง
  หายไปทั้งแถว คำตอบเก่าในประวัติจึงเหลือแต่ข้อความ ไม่มีที่มาเลย
  ซึ่งขัดกับหลักของระบบนี้ที่ว่าทุกคำตอบต้องตรวจย้อนได้

วิธีแก้:
  เก็บชื่อเอกสารกับเลขหน้าไว้ในแถวอ้างอิงเอง (denormalize) แล้วเปลี่ยน
  chunk_id เป็น nullable + SET NULL — chunk หายแต่หลักฐานว่า "คำตอบนี้
  มาจากเอกสารชื่อนี้ หน้านี้" ยังอยู่

  document_id ไม่ผูก FK โดยตั้งใจ เพราะถ้าผูกแล้วลบเอกสารทิ้ง ค่าก็จะถูก
  ล้างเป็น NULL อีก ซึ่งย้อนแย้งกับเหตุผลที่เพิ่มคอลัมน์นี้มา
  แลกกับการที่ค่านี้อาจชี้ไปยังเอกสารที่ไม่มีอยู่แล้ว — ฝั่งที่อ่านต้องเผื่อไว้
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE message_citations ADD COLUMN document_id uuid")
    op.execute("ALTER TABLE message_citations ADD COLUMN document_name VARCHAR(512)")
    op.execute("ALTER TABLE message_citations ADD COLUMN page_no INTEGER")

    # เติมย้อนหลังจาก chunk ที่ยังเหลืออยู่ — ที่หายไปแล้วกู้ไม่ได้ ยอมรับตามจริง
    op.execute(
        """
        UPDATE message_citations mc
        SET document_id = c.document_id,
            document_name = d.filename,
            page_no = c.page_no
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE mc.chunk_id = c.id
        """
    )

    op.execute("ALTER TABLE message_citations ALTER COLUMN chunk_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE message_citations DROP CONSTRAINT message_citations_chunk_id_fkey"
    )
    op.execute(
        """
        ALTER TABLE message_citations
        ADD CONSTRAINT message_citations_chunk_id_fkey
        FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE SET NULL
        """
    )


def downgrade() -> None:
    # แถวที่ chunk หายไปแล้วมี chunk_id = NULL ซึ่งกลับไปเป็น NOT NULL ไม่ได้
    # ต้องทิ้งก่อน ไม่งั้น ALTER จะล้ม — การถอย migration นี้จึงเสียข้อมูลเสมอ
    op.execute("DELETE FROM message_citations WHERE chunk_id IS NULL")
    op.execute(
        "ALTER TABLE message_citations DROP CONSTRAINT message_citations_chunk_id_fkey"
    )
    op.execute(
        """
        ALTER TABLE message_citations
        ADD CONSTRAINT message_citations_chunk_id_fkey
        FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
        """
    )
    op.execute("ALTER TABLE message_citations ALTER COLUMN chunk_id SET NOT NULL")
    op.execute("ALTER TABLE message_citations DROP COLUMN page_no")
    op.execute("ALTER TABLE message_citations DROP COLUMN document_name")
    op.execute("ALTER TABLE message_citations DROP COLUMN document_id")
