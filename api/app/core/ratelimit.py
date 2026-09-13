"""จำกัดอัตราการเรียกด้วย Redis

ทำไมต้องมีทั้งที่มีโควตาแล้ว:
  โควตาคุม "ปริมาณงานต่อวัน" ส่วน rate limit คุม "ความถี่ต่อนาที"
  คนละเรื่องกัน — endpoint แชทไม่กินโควตาเลยแต่กิน GPU ทุกครั้งที่เรียก
  บนการ์ดใบเดียวที่ตอบได้ทีละคำขอ การยิงรัวจึงทำให้คนอื่นรอทั้งคิว

ใช้ fixed window counter (INCR + EXPIRE) ไม่ใช่ sliding window
เพราะต้นทุนต่ำและแม่นพอสำหรับการกันยิงรัว ข้อเสียคือช่วงรอยต่อหน้าต่าง
อาจปล่อยได้ถึงสองเท่าของ limit ในช่วงสั้น ๆ ซึ่งรับได้ในบริบทนี้
"""
import asyncio
import time
from dataclasses import dataclass

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status

from app.core.config import settings

# cache แยกตาม event loop — connection pool ของ redis ผูกกับลูปที่สร้างมัน
# ถ้า cache ตัวเดียวข้ามลูปจะได้ "Event loop is closed" (เจอตอนรันเทสที่สร้างลูปใหม่ทุกตัว)
_clients: dict[int, aioredis.Redis] = {}


def _redis() -> aioredis.Redis:
    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        _clients[loop_id] = client
    return client


@dataclass
class Verdict:
    allowed: bool
    remaining: int
    retry_after: int


async def hit(key: str, *, limit: int, window_seconds: int) -> Verdict:
    """นับหนึ่งครั้งแล้วบอกว่าเกินหรือยัง"""
    if limit <= 0:
        return Verdict(True, limit, 0)

    bucket = int(time.time()) // window_seconds
    redis_key = f"rl:{key}:{bucket}"

    client = _redis()
    pipe = client.pipeline()
    pipe.incr(redis_key)
    # ตั้ง TTL เผื่อไว้หนึ่งหน้าต่างเพื่อให้ key หายเองแม้ระบบล่มกลางคัน
    pipe.expire(redis_key, window_seconds * 2)
    count, _ = await pipe.execute()

    remaining = max(0, limit - int(count))
    if int(count) > limit:
        elapsed = int(time.time()) % window_seconds
        return Verdict(False, 0, window_seconds - elapsed)
    return Verdict(True, remaining, 0)


def client_ip(request: Request) -> str:
    """IP ของผู้เรียก โดยเชื่อ X-Forwarded-For เฉพาะเมื่ออยู่หลัง proxy ของเราเอง

    Caddy ตั้ง header นี้ให้ ถ้าเปิด API ตรงออกอินเทอร์เน็ตโดยไม่มี proxy
    ต้องปิดการเชื่อ header นี้ ไม่งั้นใครก็ปลอม IP เพื่อเลี่ยง rate limit ได้
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: int,
    subject: str | None = None,
) -> None:
    """ใช้ใน endpoint โดยตรง — โยน 429 พร้อม Retry-After ถ้าเกิน

    subject คือสิ่งที่ใช้แยกว่าใครเป็นใคร ส่ง user id มาเมื่อรู้ว่าใครเรียก
    ถ้าไม่ส่งจะถอยไปใช้ IP

    ทำไมต้องแยก: การนับต่อ IP อย่างเดียวใช้ไม่ได้กับ endpoint ที่ต้องล็อกอิน
    เพราะคนทั้งออฟฟิศที่ออกเน็ตผ่าน NAT ตัวเดียวกันจะถูกนับรวมเป็นคนเดียว
    คนหนึ่งยิงรัวแล้วทั้งห้องใช้ไม่ได้ ซึ่งไม่ใช่สิ่งที่เพดาน "20 ครั้งต่อนาที"
    ตั้งใจจะสื่อ · พอรู้ว่าใครเรียกแล้วก็ควรนับต่อคน ไม่ใช่ต่อสายเน็ต

    ส่วน /api/auth/login ยังต้องนับต่อ IP เพราะตอนนั้นยังไม่รู้ว่าใครเรียก
    (และถ้าไปนับต่ออีเมลก็จะเปิดช่องให้ยิงรหัสผิดใส่บัญชีคนอื่นจนเขาเข้าไม่ได้)
    """
    key = subject or client_ip(request)
    verdict = await hit(f"{scope}:{key}", limit=limit, window_seconds=window_seconds)
    if not verdict.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"เรียกถี่เกินไป ลองใหม่ใน {verdict.retry_after} วินาที",
            headers={"Retry-After": str(verdict.retry_after)},
        )


async def close() -> None:
    loop_id = id(asyncio.get_running_loop())
    client = _clients.pop(loop_id, None)
    if client is not None:
        await client.aclose()
