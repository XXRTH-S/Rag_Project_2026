from app.ingestion.chunk import PageText, chunk_document, chunk_page, split_sentences
from app.ingestion.clean import (
    clean_pages,
    find_repeated_lines,
    normalize_thai,
    strip_page_artifacts,
)

# ---------- clean ----------


def test_soft_hyphen_and_zero_width_are_removed() -> None:
    assert normalize_thai("ทด­สอบ\u200bงาน") == "ทดสอบงาน"


def test_inline_whitespace_collapses_but_paragraphs_survive() -> None:
    assert normalize_thai("ก    ข\n\n\n\nค") == "ก ข\n\nค"


def test_page_number_lines_are_stripped() -> None:
    text = "เนื้อหาจริง\n- 12 -\nอีกบรรทัด\nPage 3 of 40\nหน้า 7"
    assert strip_page_artifacts(text) == "เนื้อหาจริง\nอีกบรรทัด"


def test_headers_repeated_across_pages_are_detected() -> None:
    pages = [f"บริษัท ตัวอย่าง จำกัด\nเนื้อหาหน้า {i}" for i in range(1, 6)]
    assert "บริษัท ตัวอย่าง จำกัด" in find_repeated_lines(pages)


def test_short_documents_keep_everything() -> None:
    # เอกสาร 2 หน้าบอกไม่ได้ว่าอะไรคือ header — ตัดทิ้งมั่วจะเสียเนื้อหาจริง
    pages = ["หัวเรื่อง\nเนื้อหา", "หัวเรื่อง\nเนื้อหาอื่น"]
    assert find_repeated_lines(pages) == set()


def test_long_repeated_lines_are_kept_as_content() -> None:
    long_line = "ข" * 200
    pages = [f"{long_line}\nหน้า {i}" for i in range(1, 6)]
    assert long_line not in find_repeated_lines(pages)


def test_clean_pages_removes_header_and_page_numbers_together() -> None:
    pages = [f"บริษัท ตัวอย่าง จำกัด\nเนื้อหาหน้า {i}\n- {i} -" for i in range(1, 6)]
    cleaned = clean_pages(pages)
    assert cleaned[0] == "เนื้อหาหน้า 1"
    assert all("บริษัท" not in page for page in cleaned)


# ---------- chunk ----------


def test_short_page_becomes_one_chunk() -> None:
    chunks = chunk_page(PageText(page_no=1, text="ข้อความสั้น ๆ"))
    assert len(chunks) == 1
    assert chunks[0].page_no == 1
    assert chunks[0].ordinal == 0


def test_chunks_respect_the_size_limit() -> None:
    body = "\n\n".join(f"ย่อหน้าที่ {i} " + "ก" * 100 for i in range(20))
    chunks = chunk_page(PageText(page_no=1, text=body), size=300, overlap=50)

    assert len(chunks) > 1
    # ยอมให้เกินได้เฉพาะส่วน prefix ที่เติมเข้าไป แต่ตัวเนื้อหาต้องไม่เกิน
    assert all(len(c.text) <= 300 for c in chunks)


def test_heading_context_is_attached_to_every_chunk() -> None:
    text = "# ระเบียบการลา\nพนักงานมีสิทธิลาพักร้อนปีละสิบวัน"
    chunks = chunk_page(PageText(page_no=2, text=text), doc_title="คู่มือพนักงาน")

    assert chunks[0].heading == "ระเบียบการลา"
    # chunk กลางเอกสารมักไม่มีคำที่บอกว่ากำลังพูดถึงเรื่องอะไร prefix จึงช่วย recall
    assert chunks[0].text.startswith("[คู่มือพนักงาน · ระเบียบการลา]")
    assert "ลาพักร้อน" in chunks[0].text


def test_separate_headings_start_separate_chunks() -> None:
    text = "# หัวข้อ ก\nเนื้อหา ก\n\n# หัวข้อ ข\nเนื้อหา ข"
    chunks = chunk_page(PageText(page_no=1, text=text))
    assert [c.heading for c in chunks] == ["หัวข้อ ก", "หัวข้อ ข"]


def test_ordinals_are_continuous_across_pages() -> None:
    pages = [
        PageText(page_no=1, text="\n\n".join("ก" * 200 for _ in range(4))),
        PageText(page_no=2, text="\n\n".join("ข" * 200 for _ in range(4))),
    ]
    chunks = chunk_document(pages, size=300, overlap=40)

    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert {c.page_no for c in chunks} == {1, 2}


def test_source_is_carried_through_for_debugging_retrieval() -> None:
    pages = [
        PageText(page_no=1, text="หน้าที่อ่านจาก text layer", source="parse"),
        PageText(page_no=2, text="หน้าที่ผ่าน OCR", source="ocr"),
    ]
    chunks = chunk_document(pages)
    assert {c.page_no: c.source for c in chunks} == {1: "parse", 2: "ocr"}


def test_very_long_sentence_is_split_instead_of_dropped() -> None:
    # ประโยคเดียวที่ยาวกว่า chunk size ต้องถูกหั่น ไม่ใช่หายไป
    chunks = chunk_page(PageText(page_no=1, text="ก" * 1000), size=200, overlap=0)
    assert len(chunks) == 5
    assert sum(len(c.text) for c in chunks) == 1000


def test_thai_sentences_split_on_sentence_boundaries() -> None:
    text = "วันนี้อากาศดีมาก เราจึงออกไปเดินเล่นที่สวนสาธารณะ ตอนเย็นกลับบ้านมาทำอาหาร"
    sentences = split_sentences(text)
    assert len(sentences) >= 1
    assert "".join(sentences).replace(" ", "") == text.replace(" ", "")


def test_empty_page_produces_no_chunks() -> None:
    assert chunk_page(PageText(page_no=1, text="   \n\n  ")) == []


def test_code_comments_are_not_mistaken_for_headings() -> None:
    """คอมเมนต์ของ Python/Bash/YAML ขึ้นต้นด้วย # เหมือนหัวข้อ markdown เป๊ะ

    ถ้าไม่กันไว้ ตัวอย่างโค้ดจะถูกผ่าครึ่ง แล้วคอมเมนต์กลายเป็นชื่อหัวข้อของ chunk
    ซึ่งพังสองต่อ: โค้ดขาดจนอ่านไม่รู้เรื่อง และหัวข้อที่ผิดทำให้ค้นไม่เจอ
    """
    text = (
        "# ตัวแปรใน Python\n"
        "ประกาศได้เลยโดยไม่ต้องบอกชนิด\n"
        "\n"
        "```python\n"
        "age = 30\n"
        "# บรรทัดนี้คือคอมเมนต์\n"
        "print(age)\n"
        "```\n"
    )
    chunks = chunk_page(PageText(page_no=1, text=text))

    assert [c.heading for c in chunks] == ["ตัวแปรใน Python"]
    body = chunks[0].text
    assert "age = 30" in body
    assert "print(age)" in body, "โค้ดต้องอยู่ครบใน chunk เดียว ไม่ถูกผ่าครึ่ง"


def test_headings_after_a_closed_code_block_still_work() -> None:
    """เปิด-ปิด fence ต้องสลับสถานะถูก ไม่ใช่ปิดการตัดหัวข้อไปตลอดทั้งไฟล์"""
    text = (
        "# ส่วนที่หนึ่ง\n"
        "```python\n"
        "# คอมเมนต์\n"
        "x = 1\n"
        "```\n"
        "\n"
        "# ส่วนที่สอง\n"
        "เนื้อหาของส่วนที่สอง\n"
    )
    chunks = chunk_page(PageText(page_no=1, text=text))
    assert [c.heading for c in chunks] == ["ส่วนที่หนึ่ง", "ส่วนที่สอง"]


def test_tilde_fences_count_as_code_too() -> None:
    text = "# หัวข้อ\n~~~bash\n# คอมเมนต์ของ bash\necho hi\n~~~\n"
    chunks = chunk_page(PageText(page_no=1, text=text))
    assert [c.heading for c in chunks] == ["หัวข้อ"]
