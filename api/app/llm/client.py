"""OpenAI-compatible client ตัวเดียวใช้ได้ทั้ง Ollama และ vLLM

นี่คือเหตุผลที่ย้าย tier ได้โดยแก้แค่ .env — protocol เหมือนกัน ต่างแค่ base_url
"""
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings


class ChatClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout = timeout or settings.llm_timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        thinking = settings.llm_enable_thinking if enable_thinking is None else enable_thinking
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "max_tokens": max_tokens or settings.llm_max_tokens,
            "stream": stream,
        }
        if not thinking:
            # ต้องส่งสองแบบเพราะแต่ละ runtime รู้จักคนละตัว
            #
            # chat_template_kwargs -> vLLM
            # reasoning_effort     -> Ollama และ API ที่ทำตามสเปกของ OpenAI
            #
            # เดิมส่งแค่ chat_template_kwargs ซึ่ง **Ollama ไม่รู้จักและเพิกเฉย**
            # ผลคือ thinking ทำงานอยู่ตลอด: คำถาม "1+1 เท่ากับเท่าไหร่" สร้าง reasoning
            # ซ่อนไว้ 3,307 token ใช้เวลา 86 วินาที เทียบกับ 2 token ใน 0.6 วินาที
            # เมื่อปิดถูกวิธี — ต่างกัน 143 เท่า และเป็นต้นเหตุที่คำตอบดีเลย์
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            if settings.llm_reasoning_effort:
                payload["reasoning_effort"] = settings.llm_reasoning_effort
        return payload

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            stream=False,
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            return resp.json()

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
    ) -> AsyncIterator[str]:
        """yield เฉพาะ delta ที่เป็นข้อความ — caller เอาไปห่อเป็น SSE เอง"""
        import json

        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            stream=True,
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client, client.stream(
            "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.base_url}/models", headers=self._headers())
            resp.raise_for_status()
            # Ollama ที่ยังไม่มีโมเดลเลยตอบ {"data": null} ไม่ใช่ {"data": []}
            # .get("data", []) จึงคืน None เพราะ key มีอยู่จริง ต้องใช้ or []
            data = resp.json().get("data") or []
            return [m["id"] for m in data if isinstance(m, dict) and "id" in m]
