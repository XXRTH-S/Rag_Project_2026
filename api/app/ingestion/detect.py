"""ตัดสินว่าหน้าไหนต้องส่งเข้า OCR — **รายหน้า ไม่ใช่รายไฟล์**

นี่คือจุดที่ประหยัดเวลาที่สุดของทั้งระบบ เอกสารไทยส่วนใหญ่เป็น PDF ผสม
(บางหน้ามี text layer บางหน้าสแกน) บนการ์ด 6GB ที่ OCR ได้ ~25 วินาที/หน้า
PDF 100 หน้าที่มี text layer อยู่แล้ว 80 หน้า ลดเวลาจาก 45 นาทีเหลือ 9 นาที

ทุกอย่างในไฟล์นี้ทำงานบน CPU ล้วน ไม่แตะ GPU
"""
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.quota.page_count import IMAGE_MIMES, PDF_MIMES, UnsupportedFileType, count_visible_chars


@dataclass
class PagePlan:
    page_no: int  # นับจาก 1 ให้ตรงกับที่ผู้ใช้เห็นในโปรแกรมอ่าน PDF
    needs_ocr: bool
    text: str = ""


@dataclass
class DocumentPlan:
    pages: list[PagePlan] = field(default_factory=list)

    @property
    def total_pages(self) -> int:
        return len(self.pages)

    @property
    def ocr_pages(self) -> list[PagePlan]:
        return [p for p in self.pages if p.needs_ocr]

    @property
    def ocr_page_count(self) -> int:
        return len(self.ocr_pages)

    @property
    def estimated_seconds(self) -> float:
        """เฉพาะหน้าที่ต้อง OCR — หน้าที่ parse ตรงใช้เวลาไม่กี่มิลลิวินาที"""
        return self.ocr_page_count * settings.ocr_seconds_per_page

    def summary(self) -> str:
        saved = self.total_pages - self.ocr_page_count
        return (
            f"{self.total_pages} หน้า · OCR {self.ocr_page_count} หน้า · "
            f"ข้าม OCR ได้ {saved} หน้า · ประเมิน {self.estimated_seconds / 60:.1f} นาที"
        )


def page_needs_ocr(extracted_text: str) -> bool:
    """หน้าที่ text layer ให้ตัวอักษรน้อยเกินไป = หน้าสแกน

    นับด้วย count_visible_chars เพราะภาษาไทยมีสระ/วรรณยุกต์ที่เป็น combining mark
    ซึ่งไม่ควรนับเป็นเนื้อหา
    """
    return count_visible_chars(extracted_text) < settings.ocr_min_chars_per_page


def plan_pdf(path: Path) -> DocumentPlan:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise UnsupportedFileType("PDF ถูกเข้ารหัสไว้ เปิดอ่านไม่ได้") from exc

    plan = DocumentPlan()
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            # หน้าที่ pypdf อ่านไม่ได้ ให้ OCR ไปเลย ดีกว่าทิ้งเนื้อหาทั้งหน้า
            text = ""
        needs = page_needs_ocr(text)
        plan.pages.append(PagePlan(page_no=index, needs_ocr=needs, text="" if needs else text))
    return plan


def plan_document(path: Path, mime_type: str) -> DocumentPlan:
    mime = mime_type.lower().split(";")[0].strip()

    if mime in PDF_MIMES:
        return plan_pdf(path)

    if mime in IMAGE_MIMES:
        return DocumentPlan(pages=[PagePlan(page_no=1, needs_ocr=True)])

    # docx / txt / html มี text อยู่แล้ว ไม่ต้องแตะ GPU เลย
    return DocumentPlan(pages=[PagePlan(page_no=1, needs_ocr=False)])
