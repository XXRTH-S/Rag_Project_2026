#!/usr/bin/env python
"""เติม search_text ให้ chunk ที่มีอยู่ก่อน migration 0003

รัน:
    .\\dc.ps1 exec api python scripts/backfill_search_text.py

chunk ที่ ingest หลัง migration จะมีค่านี้อยู่แล้ว สคริปต์นี้ไว้สำหรับข้อมูลเก่า
ปลอดภัยที่จะรันซ้ำ — จะข้าม chunk ที่มีค่าแล้ว
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.document import Chunk  # noqa: E402
from app.retrieval.keywords import to_search_text  # noqa: E402

BATCH = 200


async def main() -> None:
    async with SessionLocal() as session:
        total = 0
        while True:
            rows = (
                await session.execute(
                    select(Chunk).where(Chunk.search_text.is_(None)).limit(BATCH)
                )
            ).scalars().all()
            if not rows:
                break

            for chunk in rows:
                chunk.search_text = to_search_text(chunk.text)
            await session.commit()

            total += len(rows)
            print(f"  เติมแล้ว {total} chunk")

        print(f"เสร็จ — ทั้งหมด {total} chunk")


asyncio.run(main())
