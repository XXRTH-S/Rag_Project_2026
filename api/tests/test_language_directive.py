"""เทสการกำกับภาษาของคำตอบ

ทำไมต้องตรวจภาษาในโค้ด: กฎ "ตอบเป็นภาษาเดียวกับคำถาม" ใน system prompt ไม่พอ
วัดจริง 9 ก.ย. 2026 กับ qwen3.5:4b — ถามอังกฤษ 4 ข้อ ได้คำตอบไทย 2 ข้อ
เพราะ context ที่ค้นมาเป็นไทยล้วนจึงดึงโมเดลให้ตอบไทย
"""
import uuid

import pytest

from app.llm.prompts import build_messages, detect_question_language, language_directive
from app.retrieval.search import SearchHit


def _hit() -> SearchHit:
    return SearchHit(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name="ระเบียบบริษัท.pdf",
        page_no=1,
        text="ลาพักร้อนได้ปีละสิบวันทำการ",
        source="vector",
        score=0.8,
        rank=1,
    )


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("ลาพักร้อนได้ปีละกี่วัน", "th"),
        ("กี่วัน", "th"),
        ("How many annual leave days do employees get?", "en"),
        ("per-diem?", "en"),
        # ตัวเลขและเครื่องหมายล้วน บอกภาษาไม่ได้ ต้องไม่บังคับผิด
        ("2568?", ""),
        ("", ""),
    ],
)
def test_language_detection(question: str, expected: str) -> None:
    assert detect_question_language(question) == expected


def test_thai_question_with_english_terms_stays_thai() -> None:
    """คำถามไทยที่มีศัพท์อังกฤษปน ต้องไม่ถูกตัดสินเป็นอังกฤษ
    เพราะผู้ใช้ไทยพิมพ์ "ขอ policy WFH" กันปกติ
    """
    assert detect_question_language("นโยบาย work from home เป็นอย่างไร") == "th"


def test_mostly_english_with_a_little_thai_is_left_to_the_model() -> None:
    """อังกฤษเป็นหลักแต่มีไทยปน — บังคับข้างใดข้างหนึ่งก็เสี่ยงผิด ปล่อยให้โมเดลเลือก"""
    assert detect_question_language("What is the ค่าเบี้ยเลี้ยง policy for overseas trips?") == ""


def test_english_directive_forbids_thai_outright() -> None:
    """ถ้าสั่งแค่ "answer in English" โมเดลยังติดคำลงท้ายไทยมาด้วย
    ต้องห้ามภาษาไทยตรง ๆ เพราะกฎคำลงท้ายอยู่ใน system prompt คนละที่
    """
    d = language_directive("What is the per-diem?")
    assert "English" in d
    assert "Thai" in d


def test_directive_is_the_last_thing_the_model_reads() -> None:
    """โมเดลเล็กให้น้ำหนักกับส่วนท้าย prompt มากกว่าต้น
    ถ้าคำสั่งไม่ได้อยู่ท้ายสุด context ที่เป็นไทยจะกลบมันได้
    """
    msgs = build_messages("What is the per-diem?", [_hit()])
    assert msgs[-1]["content"].rstrip().endswith("Do not use Thai in the answer.")


def test_thai_question_gets_a_thai_directive() -> None:
    msgs = build_messages("ลาพักร้อนได้กี่วัน", [_hit()])
    assert msgs[-1]["content"].rstrip().endswith("(ตอบเป็นภาษาไทย)")


def test_undetectable_language_adds_nothing() -> None:
    """ไม่รู้ภาษาแล้วยังใส่คำสั่ง = บังคับผิดครึ่งหนึ่งของเวลา ยอมไม่ใส่ดีกว่า"""
    assert language_directive("2568?") == ""
    msgs = build_messages("2568?", [_hit()])
    assert msgs[-1]["content"].rstrip().endswith("2568?")


def test_question_still_reaches_the_model_verbatim() -> None:
    """คำสั่งกำกับภาษาต้องไม่กลืนคำถามหาย"""
    msgs = build_messages("What is the per-diem?", [_hit()])
    assert "What is the per-diem?" in msgs[-1]["content"]
