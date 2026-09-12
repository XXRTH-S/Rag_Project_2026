"""สร้าง embedding และนับ token จริงจาก TEI

chunk.py แบ่งด้วยจำนวน "ตัวอักษร" เพราะเร็วและไม่ต้องโหลด tokenizer มาไว้ในโปรเซส
แต่ token_count ที่เก็บลง DB ต้องเป็นค่าจริงจาก tokenizer ของ bge-m3
จึงดึงทีเดียวทั้งเอกสารด้วย /tokenize หนึ่งครั้ง
"""
import httpx

from app.core.config import settings
from app.retrieval.embeddings import EmbeddingClient

# ต้องไม่เกิน --max-client-batch-size ที่ตั้งไว้ใน docker-compose.yml
# ซึ่งลดลงเหลือ 16 เพื่อไม่ให้ TEI ถูก OOM kill บน WSL VM ที่มี RAM จำกัด
BATCH_SIZE = 16


async def embed_texts(texts: list[str]) -> list[list[float]]:
    client = EmbeddingClient()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        vectors.extend(await client.embed(texts[start : start + BATCH_SIZE]))
    return vectors


async def count_tokens(texts: list[str]) -> list[int]:
    """นับ token ด้วย tokenizer ตัวจริงของโมเดล

    ถ้า endpoint ไม่รองรับ /tokenize ให้คืน 0 แทนการล้มทั้ง job —
    token_count ใช้สำหรับ analytics ไม่ใช่สำหรับความถูกต้องของ retrieval
    """
    base = settings.embedding_base_url.rstrip("/")
    counts: list[int] = []

    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            try:
                resp = await client.post(f"{base}/tokenize", json={"inputs": batch})
                resp.raise_for_status()
                counts.extend(len(tokens) for tokens in resp.json())
            except (httpx.HTTPError, ValueError, TypeError):
                counts.extend(0 for _ in batch)

    return counts
