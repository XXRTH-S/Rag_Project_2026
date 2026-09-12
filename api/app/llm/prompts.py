"""Prompt สำหรับตอบคำถามจาก context

เขียนสั้นและสั่งตรง เพราะโมเดล 4B ทำตามคำสั่งยาว ๆ ได้แย่กว่าโมเดลใหญ่มาก
ทุกข้อในนี้มีเหตุผลจากพฤติกรรมที่พบจริงกับโมเดลเล็ก
"""

import re

from app.core.config import settings
from app.retrieval.search import SearchHit  # noqa: TC001


def _particle() -> str:
    return settings.bot_polite_particle.strip()


def _politeness_rules() -> str:
    """กฎเรื่องความสุภาพ — ใส่เฉพาะเมื่อตั้งคำลงท้ายไว้

    ผูกกับ "เมื่อตอบเป็นภาษาไทย" โดยตั้งใจ เพราะกฎข้ออื่นบอกให้ตอบภาษาเดียวกับคำถาม
    ถ้าใครถามเป็นอังกฤษแล้วเติม ครับ/ค่ะ ต่อท้ายจะกลายเป็นคำตอบที่แปลก
    และย้ำว่าให้ลงท้าย "คำตอบ" ไม่ใช่ทุกประโยค เพราะโมเดลเล็กมักใส่ซ้ำจนอ่านรำคาญ
    """
    particle = _particle()
    if not particle:
        return ""
    return (
        f'\n6. เมื่อตอบเป็นภาษาไทย ให้ใช้สรรพนามแทนตัวเองว่า "เรา" และลงท้ายคำตอบ'
        f'ด้วย "{particle}" หนึ่งครั้ง ไม่ต้องใส่ทุกประโยค'
        f"\n7. ใช้น้ำเสียงสุภาพเป็นมิตร แต่ไม่ต้องเกริ่นนำหรือขอบคุณก่อนเข้าเรื่อง"
    )


def _build_default_prompt() -> str:
    return (
        "คุณคือผู้ช่วยตอบคำถามจากเอกสารภายในองค์กร\n"
        "\n"
        "กฎที่ต้องทำตามเสมอ:\n"
        "1. ตอบจากข้อมูลใน <context> เท่านั้น ห้ามใช้ความรู้ภายนอก\n"
        "2. ทุกประโยคที่มีข้อมูลจากเอกสาร ต้องระบุที่มาเป็น [1] [2] ตามหมายเลขใน <context>\n"
        f'3. ถ้า <context> ไม่มีคำตอบ ให้ตอบว่า "{_no_context_answer()}" เท่านั้น ห้ามเดา\n'
        "4. ตอบเป็นภาษาเดียวกับคำถาม\n"
        "5. ตอบให้สั้นและตรงคำถาม" + _politeness_rules()
    )


def _no_context_answer() -> str:
    particle = _particle()
    return f"ไม่พบข้อมูลนี้ในเอกสารที่มีอยู่{particle}" if particle else "ไม่พบข้อมูลนี้ในเอกสารที่มีอยู่"


DEFAULT_SYSTEM_PROMPT = _build_default_prompt()
NO_CONTEXT_ANSWER = _no_context_answer()

# แกนของประโยคปฏิเสธ ใช้ตรวจว่าโมเดลตอบว่าไม่รู้หรือไม่
# จับแค่แกน ไม่เทียบทั้งประโยค เพราะโมเดล 4B ตัดคำท้ายทิ้งบ้าง — เจอจริง
# "ไม่พบข้อมูลนี้ในเอกสารที่มีครับ" แทนที่จะเป็น "...ในเอกสารที่มีอยู่ครับ"
_REFUSAL_CORE = "ไม่พบข้อมูล"


def looks_like_refusal(answer: str) -> bool:
    """คำตอบนี้คือการบอกว่าไม่รู้ใช่ไหม

    ต้องรู้เพราะ analytics ตอบคำถามว่า "คลังความรู้ยังขาดเรื่องอะไร" ได้จาก
    ธงนี้เท่านั้น ถ้านับเฉพาะตอน retrieval ไม่เจอ chunk เลย จะมองไม่เห็นเคสที่
    ค้นเจอของใกล้เคียงแต่ตอบไม่ได้ ซึ่งกลายเป็นเส้นทางหลักเมื่อคลังมีหลายหมวด
    (ถามเรื่อง Rust แล้วไปเจอ chunk เรื่องตัวแปรของ Go — ใกล้พอจะผ่านเกณฑ์
    แต่ไม่มีคำตอบจริง)

    ข้อจำกัด: ถ้าตั้ง prompt config ให้ปฏิเสธด้วยถ้อยคำอื่นทั้งหมด การตรวจนี้จะพลาด
    """
    return _REFUSAL_CORE in answer

# ข้อความที่ระบบเขียนเองก็ต้องสุภาพให้เข้าชุดกับคำตอบของโมเดล
# ไม่งั้นผู้ใช้จะเจอน้ำเสียงสองแบบปนกันในบทสนทนาเดียว
MODEL_UNAVAILABLE_NOTICE = (
    f"ยังไม่ได้ติดตั้งโมเดลสำหรับเรียบเรียงคำตอบ จึงยกข้อความจากเอกสารที่ตรงกับคำถามมาให้แทน{_particle()}"
)


def excerpt_fallback(hits: list[SearchHit], *, limit: int = 3) -> str:
    """คำตอบสำรองเมื่อเรียก LLM ไม่ได้ — ยกข้อความต้นทางมาตรง ๆ

    ทำให้ระบบยังมีประโยชน์แม้โมเดลตอบคำถามยังไม่พร้อม (เช่นระหว่างรอดาวน์โหลด)
    ผู้ใช้ได้เนื้อหาจริงพร้อมที่มา แค่ไม่ได้เรียบเรียงให้
    """
    lines = [MODEL_UNAVAILABLE_NOTICE, ""]
    for hit in hits[:limit]:
        page = f" หน้า {hit.page_no}" if hit.page_no else ""
        # ตัด prefix บริบทที่ chunker ใส่ไว้ออก เพราะผู้ใช้ไม่ต้องเห็น
        body = hit.text.split("\n", 1)[-1] if hit.text.startswith("[") else hit.text
        lines.append(f"[{hit.rank}] {hit.document_name}{page}")
        lines.append(body.strip()[:400])
        lines.append("")
    return "\n".join(lines).strip()


_THAI_CHARS = re.compile(r"[\u0e00-\u0e7f]")
_LATIN_CHARS = re.compile(r"[A-Za-z]")


def detect_question_language(question: str) -> str:
    """คืน "th", "en" หรือ "" เมื่อบอกไม่ได้

    ตรวจในโค้ด ไม่ปล่อยให้โมเดลตัดสินเอง เพราะ context ที่ค้นมาเป็นภาษาไทยล้วน
    จึงดึงโมเดลให้ตอบไทยแม้คำถามเป็นอังกฤษ วัดจริง 9 ก.ย. 2026 กับ qwen3.5:4b:
    ถามอังกฤษ 4 ข้อ ได้คำตอบไทย 2 ข้อ ทั้งที่กฎข้อ 4 สั่งให้ตอบภาษาเดียวกับคำถามอยู่แล้ว

    นับช่วงรหัสอักขระแทนไลบรารีตรวจภาษา เพราะคำถามสั้น ๆ อย่าง "กี่วัน"
    ทำให้ตัวตรวจแบบสถิติเดาพลาดง่าย แต่ช่วงรหัสอักขระไม่พลาด
    """
    thai = len(_THAI_CHARS.findall(question))
    latin = len(_LATIN_CHARS.findall(question))
    if thai and thai >= latin:
        return "th"
    if latin and not thai:
        return "en"
    # ปนกันโดยมีไทยน้อยกว่า เช่น "ขอ policy ของ WFH" — ปล่อยให้โมเดลเลือกเอง
    return ""


def language_directive(question: str) -> str:
    """คำสั่งกำกับภาษา วางไว้ท้ายสุดของ user message

    อยู่ท้ายเพราะโมเดลเล็กให้น้ำหนักกับส่วนท้าย prompt มากกว่าต้น
    กฎข้อ 4 ใน system prompt สั่งเรื่องนี้อยู่แล้วแต่ไม่พอ — อยู่ไกลจากคำถามเกินไป
    """
    lang = detect_question_language(question)
    if lang == "en":
        # ห้ามภาษาไทยตรง ๆ ไม่งั้นได้คำตอบอังกฤษที่ยังติดคำลงท้ายไทยมาด้วย
        return "\n\nAnswer in English. Do not use Thai in the answer."
    if lang == "th":
        return "\n\n(ตอบเป็นภาษาไทย)"
    return ""


def format_context(hits: list[SearchHit]) -> str:
    blocks = []
    for hit in hits:
        page = f" หน้า {hit.page_no}" if hit.page_no else ""
        blocks.append(f"[{hit.rank}] ({hit.document_name}{page})\n{hit.text}")
    return "\n\n".join(blocks)


def build_messages(
    question: str,
    hits: list[SearchHit],
    *,
    system_prompt: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT}]

    # ประวัติการสนทนาอยู่ก่อน context เสมอ เพื่อให้ context ที่เพิ่ง retrieve มา
    # อยู่ใกล้คำถามที่สุด — โมเดลเล็กให้น้ำหนักกับส่วนท้าย prompt มากกว่า
    if history:
        messages.extend(history)

    messages.append(
        {
            "role": "user",
            "content": (
                f"<context>\n{format_context(hits)}\n</context>"
                f"\n\nคำถาม: {question}" + language_directive(question)
            ),
        }
    )
    return messages
