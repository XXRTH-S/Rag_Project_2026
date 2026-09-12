"""โหลดโมเดลเข้า VRAM ล่วงหน้าตอน API เริ่มทำงาน

ทำไม: วัดจริงบน RTX 3050 พบว่าคำถามแรกตอนโมเดลไม่อยู่ใน VRAM ใช้เวลา 36.8 วินาที
กว่า token แรกจะออกมา ขณะที่ตอนอุ่นแล้วใช้ 15.2 วินาที ส่วนต่าง 21 วินาทีคือเวลาโหลด
ผู้ใช้ที่เจอหน้าจอนิ่งขนาดนั้นจะคิดว่าระบบค้างแล้วถามซ้ำ

ยิงแบบไม่รอผล — startup ต้องไม่ช้าลงและต้องไม่ล้มถ้าโมเดลยังไม่ได้ pull
"""
import asyncio
import logging

import httpx

from app.core.config import settings
from app.llm.client import ChatClient

log = logging.getLogger("app.llm.warmup")


async def warm_model() -> None:
    if not settings.llm_warmup_on_start:
        return

    try:
        client = ChatClient()
        # ขอ token เดียวพอ — จุดประสงค์คือให้ Ollama โหลด weight เข้า VRAM ไม่ใช่เอาคำตอบ
        await client.complete(
            [{"role": "user", "content": "hi"}],
            max_tokens=1,
            temperature=0.0,
        )
        log.info("โหลดโมเดล %s เข้า VRAM แล้ว พร้อมตอบคำถามแรกทันที", settings.llm_model)
    except httpx.HTTPError as exc:
        # ยังไม่ได้ pull โมเดล หรือ Ollama ยังไม่ขึ้น — ไม่ใช่เหตุให้ API เริ่มไม่ได้
        log.warning("warmup ไม่สำเร็จ (ไม่กระทบการทำงาน): %s", exc)


def schedule_warmup() -> None:
    """เรียกจาก lifespan — ไม่ await เพื่อไม่ให้ startup ช้าลง"""
    task = asyncio.create_task(warm_model())
    # เก็บ reference ไว้กัน GC เก็บ task ไปกลางคัน
    _background.add(task)
    task.add_done_callback(_background.discard)


_background: set[asyncio.Task] = set()
