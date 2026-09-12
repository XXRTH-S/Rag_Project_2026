"""เทส client ที่คุยกับ Ollama/vLLM โดยไม่ต้องมีเซิร์ฟเวอร์จริง"""
import httpx

from app.llm.client import ChatClient


async def _list_models_with_payload(monkeypatch, payload) -> list[str]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    return await ChatClient(base_url="http://fake:11434/v1").list_models()


async def test_empty_ollama_returns_no_models(monkeypatch) -> None:
    """Ollama ที่ยังไม่มีโมเดลตอบ data: null ไม่ใช่ list ว่าง

    ถ้าไม่รองรับเคสนี้ /health/deep จะพังเป็น 500 ทันทีที่เปิด ollama
    ขึ้นมาแต่ยังไม่ได้ pull โมเดล ซึ่งคือสถานะปกติของการติดตั้งครั้งแรก
    """
    assert await _list_models_with_payload(monkeypatch, {"object": "list", "data": None}) == []


async def test_missing_data_key(monkeypatch) -> None:
    assert await _list_models_with_payload(monkeypatch, {"object": "list"}) == []


async def test_models_are_listed(monkeypatch) -> None:
    payload = {"data": [{"id": "typhoon-ocr"}, {"id": "qwen3.5:4b"}]}
    assert await _list_models_with_payload(monkeypatch, payload) == ["typhoon-ocr", "qwen3.5:4b"]


async def test_malformed_entries_are_skipped(monkeypatch) -> None:
    payload = {"data": [{"id": "ok"}, {"name": "ไม่มี id"}, None]}
    assert await _list_models_with_payload(monkeypatch, payload) == ["ok"]


def test_disabling_thinking_sends_both_runtime_flags() -> None:
    """ต้องส่งทั้งสองฟิลด์เพราะแต่ละ runtime รู้จักคนละตัว

    เดิมส่งแค่ chat_template_kwargs (ของ vLLM) ซึ่ง Ollama เพิกเฉย
    thinking จึงทำงานอยู่ตลอด — คำถาม "1+1" สร้าง reasoning ซ่อน 3,307 token
    ใช้เวลา 86 วินาที เทียบกับ 2 token ใน 0.6 วินาทีเมื่อปิดถูกวิธี
    """
    payload = ChatClient()._payload(  # noqa: SLF001
        [{"role": "user", "content": "hi"}], enable_thinking=False
    )
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}, "vLLM ต้องได้ฟิลด์นี้"
    assert payload["reasoning_effort"] == "none", "Ollama ต้องได้ฟิลด์นี้ ไม่งั้น thinking ไม่ถูกปิด"


def test_thinking_flags_are_absent_when_enabled() -> None:
    payload = ChatClient()._payload(  # noqa: SLF001
        [{"role": "user", "content": "hi"}], enable_thinking=True
    )
    assert "chat_template_kwargs" not in payload
    assert "reasoning_effort" not in payload


def test_reasoning_effort_can_be_turned_off_for_strict_providers(monkeypatch) -> None:
    """ผู้ให้บริการบางเจ้าอาจปฏิเสธค่า "none" — ต้องมีทางไม่ส่งฟิลด์นี้"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_reasoning_effort", "")
    payload = ChatClient()._payload(  # noqa: SLF001
        [{"role": "user", "content": "hi"}], enable_thinking=False
    )
    assert "reasoning_effort" not in payload
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
