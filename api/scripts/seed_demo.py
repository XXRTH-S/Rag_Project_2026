"""Run inside Docker: python scripts/seed_demo.py [--fixtures]."""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.demo import DEMO_COLLECTION, credentials, demo_id, seed_users
from app.models.document import Chunk, Document, IngestionJob
from app.retrieval.embeddings import EmbeddingClient
from app.retrieval.keywords import to_search_text


async def run(fixtures=False):
    items = credentials()
    async with SessionLocal() as session:
        result = await seed_users(session, items)
        await session.commit()
        result["fixtures_created"] = 0
        if fixtures:
            for item in items:
                doc_id = uuid.uuid5(demo_id(item.index), "fixture-v1")
                if await session.get(Document, doc_id):
                    continue
                body = (
                    f"# เอกสารสมมติสำหรับ Demo {item.index:02}\n\n"
                    f"เอกสารนี้เป็นข้อมูลสมมติ ไม่อ้างอิงบุคคลหรือองค์กรจริง\n"
                    f"โครงการตัวอย่างของบัญชีนี้ชื่อ สวนความรู้ {item.index:02}\n"
                    f"งบประมาณตัวอย่างคือ {item.index * 1000} บาท ระยะเวลาดำเนินงาน 14 วัน\n"
                    "ขั้นตอนการทำงานคือรวบรวมเอกสาร ตรวจสอบข้อมูล และสรุปผล\n"
                )
                vector = await EmbeddingClient().embed_one(body)
                folder = Path(settings.upload_dir).resolve() / str(demo_id(item.index))
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{doc_id}.md"
                path.write_text(body, encoding="utf8")
                doc = Document(
                    id=doc_id,
                    owner_id=demo_id(item.index),
                    filename=f"demo-{item.index:02}-guide.md",
                    mime_type="text/markdown",
                    storage_path=str(path),
                    size_bytes=len(body.encode()),
                    page_count=1,
                    status="ready",
                    collection=DEMO_COLLECTION,
                )
                session.add(doc)
                await session.flush()
                session.add(
                    Chunk(
                        document_id=doc_id,
                        owner_id=doc.owner_id,
                        ordinal=0,
                        text=body,
                        page_no=1,
                        source="parse",
                        embedding=vector,
                        search_text=to_search_text(body),
                        meta={"synthetic": True},
                    )
                )
                now = datetime.now(UTC)
                session.add(
                    IngestionJob(
                        document_id=doc_id,
                        stage="done",
                        progress=100,
                        pages_total=1,
                        pages_done=1,
                        queue="default",
                        started_at=now,
                        finished_at=now,
                        gpu_seconds=0,
                    )
                )
                await session.commit()
                result["fixtures_created"] += 1
        print(json.dumps(result))
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.fixtures))
