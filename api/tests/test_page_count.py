import zipfile
from pathlib import Path

import pytest

from app.quota.page_count import (
    UnsupportedFileType,
    count_pages,
    count_visible_chars,
)


def test_image_is_one_page(tmp_path: Path) -> None:
    f = tmp_path / "scan.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = count_pages(f, "image/png")
    assert result.pages == 1
    assert result.estimated is False


def test_thai_combining_marks_are_not_counted() -> None:
    # "เสื้อ" มีสระและวรรณยุกต์ที่ซ้อนบนพยัญชนะ ไม่ได้กินความกว้างเพิ่ม
    # ถ้านับรวมจะประเมินจำนวนหน้าเกินจริงราว 20-25%
    assert count_visible_chars("เสื้อ") < len("เสื้อ")
    assert count_visible_chars("abc") == 3


def test_whitespace_is_not_counted() -> None:
    assert count_visible_chars("a b\nc\t") == 3


def test_text_estimate_rounds_up(tmp_path: Path) -> None:
    f = tmp_path / "note.txt"
    f.write_text("ก" * 3001, encoding="utf-8")
    result = count_pages(f, "text/plain")
    assert result.pages == 2
    assert result.estimated is True


def test_empty_text_still_counts_as_one_page(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    assert count_pages(f, "text/plain").pages == 1


def test_html_tags_are_stripped_before_counting(tmp_path: Path) -> None:
    f = tmp_path / "page.html"
    body = "<p>สวัสดี</p>"
    f.write_text("<html><style>x{}</style>" + body * 200 + "</html>", encoding="utf-8")
    result = count_pages(f, "text/html")
    # ถ้าไม่ตัด tag ออก จำนวนตัวอักษรจะพองจนหักโควตาเกินจริงหลายเท่า
    assert result.pages == 1


def test_docx_estimates_from_document_xml(tmp_path: Path) -> None:
    f = tmp_path / "doc.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("word/document.xml", "<w:t>" + "ก" * 6100 + "</w:t>")
    result = count_pages(
        f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert result.pages == 3
    assert result.estimated is True


def test_broken_docx_raises(tmp_path: Path) -> None:
    f = tmp_path / "broken.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("nothing.txt", "x")
    with pytest.raises(UnsupportedFileType):
        count_pages(
            f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )


def test_unsupported_mime_raises(tmp_path: Path) -> None:
    f = tmp_path / "movie.mp4"
    f.write_bytes(b"\x00")
    with pytest.raises(UnsupportedFileType):
        count_pages(f, "video/mp4")
