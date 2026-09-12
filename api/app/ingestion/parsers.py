"""ดึงข้อความจากไฟล์ที่มี text อยู่แล้ว — ไม่แตะ GPU เลย"""
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.quota.page_count import PDF_MIMES, UnsupportedFileType

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        try:
            xml = zf.read("word/document.xml")
        except KeyError as exc:
            raise UnsupportedFileType("ไฟล์ .docx เสียหาย ไม่พบ word/document.xml") from exc

    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for para in root.iter(f"{W_NS}p"):
        # ข้อความในย่อหน้าเดียวถูกซอยเป็นหลาย run ตามการจัดรูปแบบ ต้องต่อกลับให้ครบ
        # ไม่งั้นคำเดียวที่มีตัวหนาบางส่วนจะถูกตัดเป็นคนละชิ้น
        text = "".join(node.text or "" for node in para.iter(f"{W_NS}t"))
        paragraphs.append(text.strip())

    # ย่อหน้าว่างคือขอบเขตย่อหน้าจริงในไฟล์ Word เก็บไว้ให้ chunk.py ใช้
    return "\n\n".join(p for p in paragraphs if p) or ""


def extract_html(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", raw)
    from html import unescape

    return unescape(text)


def extract_text(path: Path, mime_type: str) -> str:
    mime = mime_type.lower().split(";")[0].strip()

    if mime in PDF_MIMES:
        raise UnsupportedFileType("PDF ต้องผ่าน detect รายหน้า ไม่ใช่ extract_text")

    if path.suffix.lower() == ".docx" or mime.endswith("wordprocessingml.document"):
        return extract_docx(path)

    raw = path.read_text(encoding="utf-8", errors="ignore")
    if mime in {"text/html", "application/xhtml+xml"}:
        return extract_html(raw)
    return raw
