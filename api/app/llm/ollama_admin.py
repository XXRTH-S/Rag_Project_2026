"""ตรวจว่าโมเดลรันบน GPU จริงหรือหล่นไป CPU

นี่คือกับดักเงียบที่สุดของ tier LOCAL: ถ้า VRAM ไม่พอ Ollama จะไม่ error
แต่ย้ายบาง layer ไปรันบน CPU แล้วช้าลง 5-10 เท่าโดยไม่บอกอะไรเลย
OCR ที่ควรใช้ 25 วิ/หน้าจะกลายเป็น 3 นาที/หน้าแบบเงียบ ๆ

เทียบเท่าคำสั่ง `ollama ps` แต่เรียกได้จากโค้ด เพื่อ log ลง ingestion_jobs.processor_note
ทุกครั้งที่ job เริ่ม
"""
from dataclasses import dataclass

import httpx

from app.core.config import settings


@dataclass
class LoadedModel:
    name: str
    size_bytes: int
    size_vram_bytes: int

    @property
    def gpu_percent(self) -> int:
        if self.size_bytes <= 0:
            return 0
        return round(100 * self.size_vram_bytes / self.size_bytes)

    @property
    def fully_on_gpu(self) -> bool:
        # เผื่อ 2% ให้ค่าที่ Ollama ปัดเศษ
        return self.gpu_percent >= 98

    def summary(self) -> str:
        return f"{self.name}: {self.gpu_percent}% GPU"


def _native_base_url() -> str:
    """base_url ใน .env ลงท้ายด้วย /v1 แต่ /api/ps เป็น endpoint ดั้งเดิมของ Ollama"""
    return settings.llm_base_url.rstrip("/").removesuffix("/v1")


async def loaded_models(timeout: int = 5) -> list[LoadedModel]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{_native_base_url()}/api/ps")
        resp.raise_for_status()
        return [
            LoadedModel(
                name=m.get("name", "?"),
                size_bytes=int(m.get("size", 0)),
                size_vram_bytes=int(m.get("size_vram", 0)),
            )
            for m in resp.json().get("models", [])
        ]


async def loaded_models_safe() -> list[LoadedModel] | str:
    """เรียก /api/ps ครั้งเดียวแล้วเอาผลไปใช้ทั้งสรุปและคำเตือน

    เดิมแยกเป็นสองฟังก์ชันที่ต่างคนต่างยิง ทำให้ทุกครั้งที่เช็ค health
    ต้องรอ network สองรอบโดยไม่จำเป็น
    """
    try:
        return await loaded_models()
    except httpx.HTTPError as exc:
        return f"unavailable ({type(exc).__name__})"


def summarize(models: list[LoadedModel] | str) -> str:
    """สตริงสั้น ๆ ไว้เก็บลง ingestion_jobs.processor_note"""
    if isinstance(models, str):
        return models
    if not models:
        return "no model loaded"
    return "; ".join(m.summary() for m in models)


def spill_warning(models: list[LoadedModel] | str) -> str | None:
    """คืนข้อความเตือนถ้ามีโมเดลหล่นไป CPU, None ถ้าทุกอย่างปกติ"""
    if isinstance(models, str):
        return None
    spilled = [m for m in models if not m.fully_on_gpu]
    if not spilled:
        return None
    detail = "; ".join(m.summary() for m in spilled)
    return (
        f"โมเดลบางส่วนรันบน CPU ({detail}) — จะช้ากว่าปกติ 5-10 เท่า "
        "ลองปิด browser เพื่อคืน VRAM หรือลด quantization ลง"
    )


async def processor_note() -> str:
    return summarize(await loaded_models_safe())


async def warn_if_spilled_to_cpu() -> str | None:
    return spill_warning(await loaded_models_safe())
