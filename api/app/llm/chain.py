"""เรียก LLM ตามลำดับ ตัวหลักล้มก็ใช้ตัวสำรอง

ทำไมถึงทำได้ง่าย: ทั้ง Ollama, vLLM และ API เจ้าต่าง ๆ พูด OpenAI-compatible
เหมือนกันหมด ต่างแค่ base_url กับ api_key จึงสลับกันได้โดยไม่ต้องแก้ตรรกะ

การใช้งานทั่วไป:
  ตัวหลัก = API ที่เร็วและฉลาดกว่า · ตัวสำรอง = โมเดลในเครื่องที่ไม่มีค่าใช้จ่าย
  เวลา key หมดโควตา โดน rate limit หรือเน็ตล่ม ระบบยังตอบได้ต่อ

ข้อควรระวังเรื่อง streaming:
  ถ้าตัวหลักเริ่มส่ง token ออกไปแล้วค่อยตาย จะสลับไปตัวสำรองไม่ได้
  เพราะผู้ใช้จะเห็นคำตอบซ้อนกันสองชุด จึงสลับได้เฉพาะตอนที่ยังไม่มี token ออกไปเลย
"""
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.llm.client import ChatClient

log = logging.getLogger("app.llm.chain")


@dataclass
class _Breaker:
    """กันไม่ให้ทุกคำถามต้องรอ timeout ของตัวหลักที่ล่มอยู่

    เก็บในหน่วยความจำของโปรเซส ไม่ใช่ Redis — พอสำหรับ api คอนเทนเนอร์เดียว
    ถ้าขยายเป็นหลาย replica แล้วอยากให้เห็นสถานะร่วมกัน ค่อยย้ายไป Redis
    """

    failures: dict[str, int] = field(default_factory=dict)
    opened_at: dict[str, float] = field(default_factory=dict)

    def is_open(self, name: str) -> bool:
        opened = self.opened_at.get(name)
        if opened is None:
            return False
        if time.monotonic() - opened >= settings.llm_breaker_cooldown_seconds:
            self.reset(name)
            return False
        return True

    def record_failure(self, name: str) -> None:
        count = self.failures.get(name, 0) + 1
        self.failures[name] = count
        if count >= settings.llm_breaker_threshold:
            self.opened_at[name] = time.monotonic()
            log.warning(
                "หยุดเรียก %s ชั่วคราว %s วินาที (ล้มติดกัน %s ครั้ง)",
                name,
                settings.llm_breaker_cooldown_seconds,
                count,
            )

    def reset(self, name: str) -> None:
        self.failures.pop(name, None)
        self.opened_at.pop(name, None)


_breaker = _Breaker()


@dataclass
class Provider:
    name: str
    client: ChatClient


def providers() -> list[Provider]:
    """ผู้ให้บริการตามลำดับที่จะเรียก — ตัวที่ base_url ว่างถือว่าไม่ได้ตั้งค่า"""
    result: list[Provider] = []

    if settings.llm_base_url:
        result.append(Provider(name="primary", client=ChatClient()))

    if settings.llm_fallback_base_url:
        result.append(
            Provider(
                name="fallback",
                client=ChatClient(
                    base_url=settings.llm_fallback_base_url,
                    api_key=settings.llm_fallback_api_key,
                    model=settings.llm_fallback_model or settings.llm_model,
                ),
            )
        )

    return result


class ChatChain:
    """เรียกผู้ให้บริการทีละตัวจนกว่าจะสำเร็จ

    บอกได้ว่าใครเป็นคนตอบผ่าน `model_used` เพื่อให้ analytics แยกออก
    ว่าคำตอบไหนมาจาก API ไหนมาจากโมเดลในเครื่อง
    """

    def __init__(self) -> None:
        self.model_used: str | None = None
        self.provider_used: str | None = None

    def _available(self) -> list[Provider]:
        options = providers()
        usable = [p for p in options if not _breaker.is_open(p.name)]
        # ถ้าเบรกเกอร์เปิดหมดทุกตัว ยังต้องลองอย่างน้อยหนึ่งตัว ดีกว่าไม่ตอบเลย
        return usable or options

    async def complete(self, messages: list[dict[str, Any]], **kwargs) -> dict[str, Any]:
        last: Exception | None = None

        for provider in self._available():
            try:
                response = await provider.client.complete(messages, **kwargs)
            except httpx.HTTPError as exc:
                log.warning("เรียก %s ไม่สำเร็จ: %s", provider.name, exc)
                _breaker.record_failure(provider.name)
                last = exc
                continue

            _breaker.reset(provider.name)
            self.model_used = provider.client.model
            self.provider_used = provider.name
            return response

        raise last if last else RuntimeError("ไม่ได้ตั้งค่า LLM provider เลย")

    async def stream(self, messages: list[dict[str, Any]], **kwargs) -> AsyncIterator[str]:
        last: Exception | None = None

        for provider in self._available():
            emitted = False
            try:
                async for delta in provider.client.stream(messages, **kwargs):
                    if not emitted:
                        # ยืนยันว่าเจ้านี้ตอบได้จริงเมื่อได้ token แรก
                        _breaker.reset(provider.name)
                        self.model_used = provider.client.model
                        self.provider_used = provider.name
                        emitted = True
                    yield delta
                return
            except httpx.HTTPError as exc:
                if emitted:
                    # ส่ง token ออกไปแล้ว สลับตอนนี้ผู้ใช้จะเห็นคำตอบซ้อนสองชุด
                    log.warning("%s ขาดกลางคัน หลังส่งคำตอบไปบางส่วนแล้ว", provider.name)
                    raise
                log.warning("เรียก %s ไม่สำเร็จ: %s", provider.name, exc)
                _breaker.record_failure(provider.name)
                last = exc
                continue

        raise last if last else RuntimeError("ไม่ได้ตั้งค่า LLM provider เลย")


def reset_breaker() -> None:
    """ล้างสถานะเบรกเกอร์ — ใช้ในเทสและตอนแก้ค่า config แล้วอยากให้ลองใหม่ทันที"""
    _breaker.failures.clear()
    _breaker.opened_at.clear()
