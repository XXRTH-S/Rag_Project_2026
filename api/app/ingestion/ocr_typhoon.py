"""Client ของ typhoon-ocr ผ่าน endpoint แบบ OpenAI-compatible

หมายเหตุสำคัญเรื่องเวอร์ชันโมเดล (ดู PLAN.md ข้อ 11.2):

- typhoon-ocr1.5-2b (ตัวที่เราใช้) เป็น single-prompt ไม่ต้องแนบ anchor text
- typhoon-ocr-7b (รุ่นเก่า) ทำงานได้เฉพาะ prompt ที่ฝัง metadata จาก get_anchor_text()
  ถ้าจะย้ายไปรุ่นนั้นต้องเปลี่ยนวิธีสร้าง prompt ไม่ใช่แค่เปลี่ยนชื่อโมเดลใน .env
"""
import base64
from dataclasses import dataclass

import httpx

from app.core.config import settings

# prompt ของ typhoon-ocr1.5 — สั่งให้คืน markdown ตรง ๆ ไม่ต้องอธิบาย
PROMPT_DEFAULT = (
    "Below is an image of a document page. Extract all the text content and return it "
    "as clean markdown. Preserve the reading order. Do not add any commentary."
)
PROMPT_STRUCTURE = (
    "Below is an image of a document page. Extract all the text content and return it as "
    "clean markdown. Render every table as a markdown table and keep form field labels "
    "together with their values. Preserve the reading order. Do not add any commentary."
)


@dataclass
class OcrResult:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None


class TyphoonOcrClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.typhoon_ocr_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.typhoon_ocr_api_key
        self.model = model or settings.typhoon_ocr_model
        self.timeout = timeout or settings.typhoon_ocr_page_timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _prompt(task_type: str) -> str:
        return PROMPT_STRUCTURE if task_type == "structure" else PROMPT_DEFAULT

    async def ocr_image_bytes(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/png",
        task_type: str | None = None,
    ) -> OcrResult:
        task = task_type or settings.typhoon_ocr_task_type
        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._prompt(task)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                        },
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": 4096,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage") or {}
        return OcrResult(
            text=(data["choices"][0]["message"]["content"] or "").strip(),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
