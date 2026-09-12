"""ทำความสะอาดข้อความหลัง OCR / parse

สองอย่างที่ทำให้ retrieval แย่ลงชัดเจนถ้าไม่จัดการ:
1. header/footer ที่ซ้ำทุกหน้า — กลายเป็น noise ที่ตรงกับทุก query
2. สระ/วรรณยุกต์ไทยที่ซ้อนผิดลำดับ — ทำให้ string เดียวกันมีหลายรูปแบบ
   แล้ว embedding ของคำเดียวกันไม่ตรงกัน
"""
import re
from collections import Counter

# เขียนเป็น escape ไม่ใช่อักขระจริง — อักขระพวกนี้มองไม่เห็นในโปรแกรมแก้ไขข้อความ
# ใครมาอ่านทีหลังจะไม่รู้ว่ามีอะไรอยู่ และแก้ผิดได้ง่าย
SOFT_HYPHEN = "­"
ZERO_WIDTH = "\u200b‌‍﻿"
# รวม non-breaking space ด้วย — OCR คืนค่านี้มาบ่อยและ \s ของ re ไม่จับใน ASCII mode
INLINE_SPACE = re.compile(r"[ \t ]+")

# บรรทัดที่มีแค่เลขหน้า เช่น "12", "- 12 -", "หน้า 12", "Page 12 of 40"
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:[-–—|]\s*)?(?:page|หน้า|น\.)?\s*\d+\s*(?:/|of|จาก)?\s*\d*\s*(?:[-–—|]\s*)?$",
    re.IGNORECASE,
)


def normalize_thai(text: str) -> str:
    """ยุบรูปแบบที่ต่างกันของข้อความเดียวกันให้เหลือรูปเดียว"""
    from pythainlp.util import normalize

    text = text.replace(SOFT_HYPHEN, "")
    for ch in ZERO_WIDTH:
        text = text.replace(ch, "")

    # normalize ทีละบรรทัด ไม่ใช่ทั้งก้อน — pythainlp.util.normalize ยุบบรรทัดว่างทิ้ง
    # ซึ่งจะทำลายขอบเขตย่อหน้าที่ chunk.py ใช้แบ่ง chunk
    lines = [
        # pythainlp จัดลำดับสระ/วรรณยุกต์ที่ซ้อนกันผิด และตัดตัวที่ซ้ำซ้อน
        INLINE_SPACE.sub(" ", normalize(line)).strip()
        for line in text.splitlines()
    ]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip_page_artifacts(text: str) -> str:
    kept = [line for line in text.splitlines() if not _PAGE_NUMBER_LINE.match(line)]
    return "\n".join(kept).strip()


def find_repeated_lines(pages: list[str], *, min_ratio: float = 0.6) -> set[str]:
    """หาบรรทัดที่โผล่ซ้ำในหน้าส่วนใหญ่ = header/footer

    นับแบบ "กี่หน้าที่มีบรรทัดนี้" ไม่ใช่ "โผล่ทั้งหมดกี่ครั้ง" ไม่งั้นคำที่ซ้ำเยอะ
    ในหน้าเดียวจะถูกเข้าใจผิดว่าเป็น header
    """
    if len(pages) < 3:
        # เอกสารสั้นเกินกว่าจะบอกได้ว่าอะไรคือ header ตัดทิ้งมั่วจะเสียเนื้อหา
        return set()

    counter: Counter[str] = Counter()
    for page in pages:
        seen = {line.strip() for line in page.splitlines() if line.strip()}
        counter.update(seen)

    threshold = max(2, int(len(pages) * min_ratio))
    return {
        line
        for line, count in counter.items()
        # บรรทัดยาว ๆ ที่ซ้ำทุกหน้ามักเป็นเนื้อหาจริง (เช่น ข้อความในตาราง) ไม่ใช่ header
        if count >= threshold and len(line) <= 120
    }


def clean_pages(pages: list[str]) -> list[str]:
    """ทำความสะอาดทั้งเอกสารพร้อมกัน เพราะต้องเห็นทุกหน้าถึงจะรู้ว่าอะไรคือ header"""
    normalized = [normalize_thai(p) for p in pages]
    repeated = find_repeated_lines(normalized)

    cleaned: list[str] = []
    for page in normalized:
        lines = [line for line in page.splitlines() if line.strip() not in repeated]
        cleaned.append(strip_page_artifacts("\n".join(lines)))
    return cleaned
