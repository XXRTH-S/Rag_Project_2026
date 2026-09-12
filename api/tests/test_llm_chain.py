"""เทสการสลับไปใช้ LLM ตัวสำรอง

ใช้เมื่อตั้ง API เป็นตัวหลักและโมเดลในเครื่องเป็นตัวสำรอง (หรือกลับกัน)
สิ่งที่ต้องพิสูจน์: สลับได้จริง, ไม่สลับกลางคันจนคำตอบซ้อนกัน, และเบรกเกอร์ทำงาน
"""
import httpx
import pytest

from app.core.config import settings
from app.llm import chain as chain_module
from app.llm.chain import ChatChain, providers, reset_breaker


class FakeClient:
    def __init__(self, model: str, *, fails: bool = False, fail_after: int | None = None):
        self.model = model
        self.fails = fails
        self.fail_after = fail_after
        self.calls = 0

    def _boom(self) -> httpx.HTTPError:
        return httpx.ConnectError("ต่อไม่ได้")

    async def complete(self, messages, **kwargs) -> dict:
        self.calls += 1
        if self.fails:
            raise self._boom()
        return {"choices": [{"message": {"content": f"ตอบโดย {self.model}"}}]}

    async def stream(self, messages, **kwargs):
        self.calls += 1
        if self.fails:
            raise self._boom()
        for index, piece in enumerate(["ส่วนหนึ่ง ", "ส่วนสอง ", "ส่วนสาม"]):
            if self.fail_after is not None and index >= self.fail_after:
                raise self._boom()
            yield piece


def _use(monkeypatch, *clients: FakeClient) -> None:
    from app.llm.chain import Provider

    names = ["primary", "fallback", "third"]
    monkeypatch.setattr(
        chain_module,
        "providers",
        lambda: [Provider(name=names[i], client=c) for i, c in enumerate(clients)],
    )


@pytest.fixture(autouse=True)
def clean_breaker():
    reset_breaker()
    yield
    reset_breaker()


# ---------- การตั้งค่า ----------


def test_fallback_is_off_when_base_url_is_blank(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_fallback_base_url", "")
    assert [p.name for p in providers()] == ["primary"]


def test_fallback_appears_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_fallback_base_url", "http://ollama:11434/v1")
    monkeypatch.setattr(settings, "llm_fallback_model", "qwen3.5:4b")
    names = [p.name for p in providers()]
    assert names == ["primary", "fallback"]


def test_fallback_inherits_main_model_name_when_not_set(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_fallback_base_url", "http://ollama:11434/v1")
    monkeypatch.setattr(settings, "llm_fallback_model", "")
    assert providers()[1].client.model == settings.llm_model


# ---------- complete ----------


async def test_uses_primary_when_it_works(monkeypatch) -> None:
    primary = FakeClient("api-model")
    backup = FakeClient("local-model")
    _use(monkeypatch, primary, backup)

    chain = ChatChain()
    result = await chain.complete([{"role": "user", "content": "hi"}])

    assert "api-model" in result["choices"][0]["message"]["content"]
    assert chain.provider_used == "primary"
    assert backup.calls == 0


async def test_switches_to_fallback_when_primary_fails(monkeypatch) -> None:
    primary = FakeClient("api-model", fails=True)
    backup = FakeClient("local-model")
    _use(monkeypatch, primary, backup)

    chain = ChatChain()
    result = await chain.complete([{"role": "user", "content": "hi"}])

    assert "local-model" in result["choices"][0]["message"]["content"]
    assert chain.provider_used == "fallback"
    assert chain.model_used == "local-model"


async def test_raises_when_every_provider_fails(monkeypatch) -> None:
    _use(monkeypatch, FakeClient("a", fails=True), FakeClient("b", fails=True))
    with pytest.raises(httpx.HTTPError):
        await ChatChain().complete([{"role": "user", "content": "hi"}])


# ---------- stream ----------


async def test_stream_switches_before_any_token(monkeypatch) -> None:
    primary = FakeClient("api-model", fails=True)
    backup = FakeClient("local-model")
    _use(monkeypatch, primary, backup)

    chain = ChatChain()
    text = "".join([delta async for delta in chain.stream([{"role": "user", "content": "hi"}])])

    assert text == "ส่วนหนึ่ง ส่วนสอง ส่วนสาม"
    assert chain.provider_used == "fallback"


async def test_stream_does_not_switch_after_tokens_were_sent(monkeypatch) -> None:
    """สลับตอนส่ง token ไปแล้วจะทำให้ผู้ใช้เห็นคำตอบซ้อนกันสองชุด"""
    primary = FakeClient("api-model", fail_after=2)
    backup = FakeClient("local-model")
    _use(monkeypatch, primary, backup)

    chain = ChatChain()
    received = []
    with pytest.raises(httpx.HTTPError):
        async for delta in chain.stream([{"role": "user", "content": "hi"}]):
            received.append(delta)

    assert received == ["ส่วนหนึ่ง ", "ส่วนสอง "]
    assert backup.calls == 0, "ต้องไม่เรียกตัวสำรองหลังส่งคำตอบไปบางส่วนแล้ว"


# ---------- circuit breaker ----------


async def test_breaker_stops_calling_a_dead_primary(monkeypatch) -> None:
    """ไม่งั้นทุกคำถามต้องรอ timeout ของตัวหลักก่อนเสมอ"""
    monkeypatch.setattr(settings, "llm_breaker_threshold", 2)
    primary = FakeClient("api-model", fails=True)
    backup = FakeClient("local-model")
    _use(monkeypatch, primary, backup)

    for _ in range(4):
        await ChatChain().complete([{"role": "user", "content": "hi"}])

    # ล้มสองครั้งแรกแล้วเบรกเกอร์เปิด ครั้งที่สามสี่ข้ามตัวหลักไปเลย
    assert primary.calls == 2
    assert backup.calls == 4


async def test_breaker_resets_after_a_success(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_breaker_threshold", 3)
    primary = FakeClient("api-model", fails=True)
    backup = FakeClient("local-model")
    _use(monkeypatch, primary, backup)

    await ChatChain().complete([{"role": "user", "content": "hi"}])
    primary.fails = False
    await ChatChain().complete([{"role": "user", "content": "hi"}])

    chain = ChatChain()
    await chain.complete([{"role": "user", "content": "hi"}])
    assert chain.provider_used == "primary"


async def test_all_breakers_open_still_tries_rather_than_giving_up(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_breaker_threshold", 1)
    primary = FakeClient("api-model", fails=True)
    backup = FakeClient("local-model", fails=True)
    _use(monkeypatch, primary, backup)

    with pytest.raises(httpx.HTTPError):
        await ChatChain().complete([{"role": "user", "content": "hi"}])

    # เบรกเกอร์เปิดหมดแล้ว แต่ยังต้องลองอีก ดีกว่าไม่ตอบเลย
    backup.fails = False
    chain = ChatChain()
    await chain.complete([{"role": "user", "content": "hi"}])
    assert chain.provider_used == "fallback"
