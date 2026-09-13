"""นับจำนวนหน้า *ก่อน* เข้าคิว

ทำไมต้องนับก่อน: ถ้ารอนับหลัง OCR เท่ากับปล่อยให้ user เผา GPU ไป 3 ชั่วโมง
แล้วค่อยบอกว่าเกินโควตา — บนการ์ด 6GB ที่ทำได้ ~25 วินาที/หน้า นี่ไม่ใช่เรื่องเล็ก

ทุกวิธีในไฟล์นี้ต้อง **ไม่แตะ GPU และไม่ render ภาพ**
"""
import math
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/tiff", "image/bmp"}
PDF_MIMES = {"application/pdf"}
TEXT_MIMES = {
    "text/plain",
    "text/markdown",
    "text/html",
    "application/xhtml+xml",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class UnsupportedFileType(Exception):
    pass


@dataclass
class PageEstimate:
    pages: int
    estimated: bool
    detail: str


def _count_pdf_pages(path: Path) -> PageEstimate:
    """pypdf อ่านแค่ page tree ไม่ต้อง render — เร็วมากแม้ไฟล์ใหญ่"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        # ลองเปิดด้วยรหัสว่าง ซึ่งพอได้กับ PDF ที่ล็อกแค่สิทธิ์การพิมพ์
        try:
            reader.decrypt("")
        except Exception as exc:
            raise UnsupportedFileType("PDF ถูกเข้ารหัสไว้ เปิดอ่านไม่ได้") from exc
    return PageEstimate(pages=len(reader.pages), estimated=False, detail="pypdf page tree")


def _count_docx_pages(path: Path) -> PageEstimate:
    """docx ไม่มีหน่วย 'หน้า' จริง — จำนวนหน้าขึ้นกับโปรแกรมที่เปิดและฟอนต์

    จึงประเมินจากจำนวนตัวอักษร แล้วไปแก้เป็นค่าจริงตอน commit หลัง parse เสร็จ
    """
    import re
    import zipfile

    with zipfile.ZipFile(path) as zf:
        try:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
        except KeyError as exc:
            raise UnsupportedFileType("ไฟล์ .docx เสียหาย ไม่พบ word/document.xml") from exc

    text = re.sub(r"<[^>]+>", "", xml)
    return _estimate_from_text(text, source="docx")


def _estimate_from_text(text: str, *, source: str) -> PageEstimate:
    chars = count_visible_chars(text)
    pages = max(1, math.ceil(chars / settings.chars_per_page_estimate))
    return PageEstimate(
        pages=pages,
        estimated=True,
        detail=f"{source}: {chars} ตัวอักษร ÷ {settings.chars_per_page_estimate}",
    )


def count_visible_chars(text: str) -> int:
    """นับเฉพาะตัวอักษรที่กินพื้นที่จริง

    ภาษาไทยมีสระบนล่างและวรรณยุกต์ที่เป็น combining mark (Unicode category Mn)
    ซึ่งซ้อนบนพยัญชนะ ไม่ได้กินความกว้างเพิ่ม ถ้านับรวมจะประเมินจำนวนหน้า
    เกินจริงราว 20-25% แล้ว user จะโดนหักโควตาเกินโดยไม่มีเหตุผล
    """
    return sum(1 for ch in text if not unicodedata.combining(ch) and not ch.isspace())


def count_pages(path: Path, mime_type: str) -> PageEstimate:
    """คืนจำนวนหน้าสำหรับหักโควตา โดยไม่แตะ GPU"""
    mime = mime_type.lower().split(";")[0].strip()

    if mime in PDF_MIMES:
        return _count_pdf_pages(path)

    if mime in IMAGE_MIMES:
        return PageEstimate(pages=1, estimated=False, detail="image = 1 page")

    if mime in TEXT_MIMES:
        if path.suffix.lower() == ".docx":
            return _count_docx_pages(path)
        raw = path.read_text(encoding="utf-8", errors="ignore")
        if mime in {"text/html", "application/xhtml+xml"}:
            import re

            raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
            raw = re.sub(r"<[^>]+>", " ", raw)
        return _estimate_from_text(raw, source=mime)

    raise UnsupportedFileType(f"ยังไม่รองรับไฟล์ชนิด {mime}")
