from pathlib import Path

from pypdf import PdfWriter

from app.core.config import settings
from app.ingestion.detect import DocumentPlan, PagePlan, page_needs_ocr, plan_document
from app.quota.page_count import count_visible_chars


def _blank_pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)  # A4
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_empty_page_needs_ocr() -> None:
    assert page_needs_ocr("") is True


def test_page_with_real_content_skips_ocr() -> None:
    assert page_needs_ocr("ก" * (settings.ocr_min_chars_per_page + 10)) is False


def test_page_number_artifacts_still_need_ocr() -> None:
    # หน้าสแกนมักมี text layer ที่มีแค่เลขหน้าหรือ header ติดมา
    # ถ้าไม่ตั้ง threshold ระบบจะคิดว่าหน้านั้นมีเนื้อหาแล้วข้าม OCR ไป
    assert page_needs_ocr("- 12 -") is True


def test_thai_combining_marks_do_not_inflate_the_count() -> None:
    # ถ้านับ combining mark เป็นเนื้อหา หน้าที่มีข้อความน้อยมากจะถูกมองว่ามีเนื้อหาพอ
    # "เสื้อ" = 5 code points แต่นับเป็นตัวอักษรจริงแค่ 3 (ื และ ้ ซ้อนบนพยัญชนะ)
    # ซ้ำ 12 ครั้ง: ความยาวสตริง 60 เกิน threshold แต่ตัวอักษรจริง 36 ยังไม่ถึง
    just_under = "เสื้อ" * 12
    assert len(just_under) > settings.ocr_min_chars_per_page
    assert count_visible_chars(just_under) < settings.ocr_min_chars_per_page
    assert page_needs_ocr(just_under) is True


def test_blank_pdf_marks_every_page_for_ocr(tmp_path: Path) -> None:
    pdf = _blank_pdf(tmp_path / "scan.pdf", pages=3)
    plan = plan_document(pdf, "application/pdf")

    assert plan.total_pages == 3
    assert plan.ocr_page_count == 3
    assert [p.page_no for p in plan.pages] == [1, 2, 3]


def test_image_is_always_one_ocr_page(tmp_path: Path) -> None:
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    plan = plan_document(img, "image/jpeg")

    assert plan.total_pages == 1
    assert plan.ocr_page_count == 1


def test_text_formats_never_touch_ocr(tmp_path: Path) -> None:
    doc = tmp_path / "note.txt"
    doc.write_text("สวัสดี", encoding="utf-8")
    plan = plan_document(doc, "text/plain")

    assert plan.ocr_page_count == 0
    assert plan.estimated_seconds == 0


def test_eta_counts_only_pages_that_need_ocr() -> None:
    plan = DocumentPlan(
        pages=[
            PagePlan(page_no=1, needs_ocr=False, text="x" * 100),
            PagePlan(page_no=2, needs_ocr=True),
            PagePlan(page_no=3, needs_ocr=True),
        ]
    )
    assert plan.total_pages == 3
    assert plan.ocr_page_count == 2
    assert plan.estimated_seconds == 2 * settings.ocr_seconds_per_page


def test_text_from_readable_pages_is_kept(tmp_path: Path) -> None:
    # หน้าที่ข้าม OCR ต้องเก็บข้อความไว้ ไม่งั้นต้องไปอ่านซ้ำตอน chunk
    plan = DocumentPlan(pages=[PagePlan(page_no=1, needs_ocr=False, text="เนื้อหา")])
    assert plan.pages[0].text == "เนื้อหา"
    assert plan.ocr_page_count == 0
