"""เทสคำลงท้ายสุภาพใน system prompt

ค่านี้เป็นบุคลิกที่องค์กรเลือก (ครับ/ค่ะ/ไม่ใส่) จึงอ่านจาก settings
แต่ DEFAULT_SYSTEM_PROMPT ถูกคำนวณตอน import — monkeypatch settings เฉย ๆ ไม่มีผล
เทสจึงเรียกฟังก์ชันที่สร้าง prompt ตรง ๆ เพื่อให้ทดสอบได้ทุกค่า
"""
import pytest

from app.core.config import settings
from app.llm import prompts


@pytest.fixture
def particle(monkeypatch):
    def _set(value: str):
        monkeypatch.setattr(settings, "bot_polite_particle", value)

    return _set


def test_particle_appears_in_rules(particle) -> None:
    particle("ค่ะ")
    text = prompts._build_default_prompt()
    assert 'ลงท้ายคำตอบด้วย "ค่ะ"' in text
    assert "ครับ" not in text, "ต้องไม่มีคำลงท้ายที่ hardcode ไว้หลงเหลือ"


def test_particle_is_bound_to_thai_answers_only(particle) -> None:
    """กฎข้อ 4 บอกให้ตอบภาษาเดียวกับคำถาม ถ้าคำลงท้ายไม่ผูกกับ "ตอบเป็นภาษาไทย"
    คำถามภาษาอังกฤษจะได้ "...per year ครับ" ซึ่งอ่านแปลก
    """
    particle("ครับ")
    assert "เมื่อตอบเป็นภาษาไทย" in prompts._politeness_rules()


def test_particle_asked_for_once_not_every_sentence(particle) -> None:
    """โมเดล 4B มักใส่คำลงท้ายทุกประโยคจนอ่านรำคาญ ถ้าไม่ห้ามไว้"""
    particle("ครับ")
    assert "หนึ่งครั้ง" in prompts._politeness_rules()


def test_empty_particle_removes_the_rules_entirely(particle) -> None:
    """ตั้งค่าว่าง = ปิดคำลงท้าย ต้องไม่เหลือกฎเปล่า ๆ ที่ทำให้โมเดลสับสน"""
    particle("")
    assert prompts._politeness_rules() == ""
    text = prompts._build_default_prompt()
    assert "\n6." not in text
    assert prompts._no_context_answer() == "ไม่พบข้อมูลนี้ในเอกสารที่มีอยู่"


def test_whitespace_only_particle_counts_as_empty(particle) -> None:
    """.env ที่เขียน BOT_POLITE_PARTICLE= แล้วเผลอเว้นวรรค ต้องไม่ได้คำตอบที่มีช่องว่างห้อยท้าย"""
    particle("   ")
    assert prompts._politeness_rules() == ""
    assert prompts._no_context_answer() == "ไม่พบข้อมูลนี้ในเอกสารที่มีอยู่"


def test_no_context_answer_matches_the_rule_verbatim(particle) -> None:
    """ถ้าประโยคในกฎข้อ 3 ไม่ตรงกับ NO_CONTEXT_ANSWER ที่โค้ดใช้เอง
    ผู้ใช้จะเห็นข้อความ "ไม่พบข้อมูล" สองแบบ ขึ้นกับว่า retrieval ตัดทิ้งหรือ LLM ตอบ
    """
    particle("ค่ะ")
    assert f'"{prompts._no_context_answer()}"' in prompts._build_default_prompt()


def test_system_written_notice_is_polite_too() -> None:
    """ข้อความ fallback ที่โค้ดเขียนเองต้องน้ำเสียงเดียวกับคำตอบของโมเดล
    ไม่งั้นบทสนทนาเดียวจะมีสองน้ำเสียงปนกัน
    """
    assert prompts.MODEL_UNAVAILABLE_NOTICE.endswith(settings.bot_polite_particle)
