"""ตัดคำภาษาไทยสำหรับ keyword search

Postgres ตัดคำไทยไม่ได้เพราะไม่มีช่องว่างระหว่างคำ ถ้าโยนประโยคไทยเข้า to_tsvector
จะได้ token เดียวคือทั้งประโยค ค้นหาอะไรไม่เจอเลย
จึงตัดคำด้วย pythainlp ก่อนแล้วส่งเป็นข้อความคั่นช่องว่างให้ parser 'simple' จัดการ
"""
import logging
import re

log = logging.getLogger("app.retrieval.keywords")

# คำที่พบได้ทุกเอกสารจนไม่ช่วยแยกแยะ ตัดออกเพื่อลด noise ของ keyword leg
THAI_STOPWORDS = {
    "ที่", "การ", "ของ", "และ", "ใน", "เป็น", "มี", "ได้", "ให้", "จะ", "ไม่",
    "ต้อง", "กับ", "หรือ", "แล้ว", "ก็", "โดย", "ซึ่ง", "จาก", "นี้", "นั้น",
    "อยู่", "ๆ", "คือ", "ว่า", "ถ้า", "เมื่อ", "เพื่อ", "ตาม", "ทุก",
}

_KEEP = re.compile(r"[฀-๿a-zA-Z0-9]")
# ทางถอยเมื่อตัวตัดคำใช้ไม่ได้ — แยกตามช่องว่างและเครื่องหมายวรรคตอน
# ใช้กับไทยได้ไม่ดีเพราะไทยไม่มีช่องว่างคั่นคำ แต่ยังได้คำอังกฤษและตัวเลข
_ROUGH_SPLIT = re.compile(r"[^฀-๿a-zA-Z0-9]+")

# เตือนครั้งเดียวพอ — ถ้าเตือนทุกคำขอ log จะท่วมจนอ่านอะไรไม่เจอ
_warned_about_tokenizer = False


def _rough_tokens(text: str) -> list[str]:
    global _warned_about_tokenizer
    if not _warned_about_tokenizer:
        log.warning(
            "ตัวตัดคำภาษาไทยใช้ไม่ได้ ใช้การแยกแบบหยาบแทน — "
            "keyword leg จะหาคำไทยได้แย่ลง · ตั้ง PYTHAINLP_DATA_DIR "
            "ไปยังไดเรกทอรีที่เขียนได้ (บน serverless ใช้ /tmp)"
        )
        _warned_about_tokenizer = True
    return [t for t in _ROUGH_SPLIT.split(text) if t]


def tokenize(text: str) -> list[str]:
    """ตัดคำสำหรับ keyword leg

    ถ้าตัวตัดคำใช้ไม่ได้ให้ถอยไปแยกแบบหยาบ ไม่ใช่โยน exception ออกไป

    เหตุผล: keyword leg เป็นส่วนเสริมของ vector search ไม่ใช่ส่วนที่ขาดไม่ได้
    การล้มทั้งคำขอเพราะส่วนเสริมใช้ไม่ได้เป็นการแลกที่ผิด · เจอจริงบน Vercel
    ตอน pythainlp เขียนไดเรกทอรีข้อมูลใน HOME ไม่ได้ (ระบบไฟล์อ่านอย่างเดียว)
    แล้วทุกคำถามล้มทั้งที่ vector search ทำงานได้ปกติ
    """
    try:
        from pythainlp.tokenize import word_tokenize

        tokens = word_tokenize(text, keep_whitespace=False)
    except Exception:  # noqa: BLE001
        tokens = _rough_tokens(text)

    return [
        token
        for raw in tokens
        if (token := raw.strip().lower())
        and _KEEP.search(token)
        and token not in THAI_STOPWORDS
    ]


def to_search_text(text: str) -> str:
    """ข้อความที่ตัดคำแล้วสำหรับเก็บลงคอลัมน์ search_text"""
    return " ".join(tokenize(text))


def to_tsquery(question: str) -> str:
    """สร้าง tsquery แบบ OR — ต้องการให้ chunk ที่มีคำสำคัญบางคำก็ยังติดอันดับ

    ใช้ OR ไม่ใช่ AND เพราะคำถามมักมีคำที่ไม่ปรากฏในเอกสารปนมาด้วย
    ถ้าใช้ AND จะไม่เจออะไรเลย การจัดอันดับปล่อยให้ ts_rank กับ RRF จัดการ
    """
    tokens = tokenize(question)
    # กันอักขระที่มีความหมายพิเศษใน tsquery
    safe = [re.sub(r"[^฀-๿a-zA-Z0-9]", "", t) for t in tokens]
    return " | ".join(t for t in safe if t)
