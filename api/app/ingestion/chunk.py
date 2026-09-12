"""แบ่ง chunk แบบรู้ขอบเขตประโยคภาษาไทย

ภาษาไทยไม่มีช่องว่างระหว่างคำ splitter ที่ตัดตามความยาวอย่างเดียวจะตัดกลางคำ
แล้วได้ chunk ที่ขึ้นต้นด้วยเศษคำ ซึ่งทำให้ embedding เพี้ยน

ลำดับการตัด: หัวข้อ -> ย่อหน้า -> ประโยค (pythainlp) -> ตัดตามความยาว

หมายเหตุเรื่องหน่วย: CHUNK_SIZE นับเป็น **ตัวอักษร** ไม่ใช่ token
bge-m3 รับได้ 8192 token ส่วน chunk ของเราอยู่ราว 800 ตัวอักษร จึงไม่มีทางล้น
ส่วน token_count ที่เก็บลง DB ดึงค่าจริงจาก /tokenize ของ TEI ตอน embed
"""
import re
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import settings

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# ``` หรือ ~~~ เปิด/ปิด code block · รับ indent ได้เพราะโค้ดในลิสต์จะย่อหน้าเข้ามา
_CODE_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class TextChunk:
    ordinal: int
    text: str
    page_no: int | None
    source: str  # parse | ocr
    heading: str | None = None

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class PageText:
    page_no: int
    text: str
    source: str = "parse"


@lru_cache(maxsize=1)
def _sentence_engine() -> str:
    """crfcut แม่นกว่าแต่ต้องมี python-crfsuite ซึ่งเป็น extra ของ pythainlp

    ถ้าไม่มี ใช้ whitespace+newline แทน — ในภาษาไทยช่องว่างทำหน้าที่คั่นประโยค
    อยู่แล้ว จึงเป็น fallback ที่ยังใช้ได้จริง ไม่ใช่การถอยไปตัดตามความยาว
    ติดตั้ง python-crfsuite เมื่อไหร่ ระบบจะเปลี่ยนไปใช้ crfcut เองโดยไม่ต้องแก้โค้ด
    """
    from pythainlp.tokenize import sent_tokenize

    try:
        sent_tokenize("ทดสอบระบบ", engine="crfcut")
    except Exception:  # noqa: BLE001
        return "whitespace+newline"
    return "crfcut"


def split_sentences(text: str) -> list[str]:
    from pythainlp.tokenize import sent_tokenize

    parts = [s.strip() for s in sent_tokenize(text, engine=_sentence_engine()) if s.strip()]
    # คืนลิสต์ว่างได้ถ้าข้อความสั้นหรือเป็นภาษาอังกฤษล้วน
    return parts or ([text.strip()] if text.strip() else [])


def _hard_split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _pack(pieces: list[str], size: int, overlap: int) -> list[str]:
    """รวมชิ้นเล็กให้เต็ม chunk แล้วทับซ้อนท้าย chunk ก่อนหน้า"""
    chunks: list[str] = []
    current = ""

    for piece in pieces:
        if len(piece) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(piece, size))
            continue

        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= size:
            current = candidate
        else:
            chunks.append(current)
            # ทับซ้อนโดยตัดที่ขอบช่องว่าง ไม่ให้ chunk ถัดไปขึ้นต้นด้วยเศษคำ
            tail = current[-overlap:] if overlap else ""
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1 :]
            current = f"{tail} {piece}".strip() if tail else piece

    if current:
        chunks.append(current)
    return chunks


def _blocks_with_headings(text: str) -> list[tuple[str | None, str]]:
    """แยกเป็น (หัวข้อ, เนื้อหา) ตามหัวข้อ markdown ที่ typhoon-ocr คืนมา

    บรรทัดใน code block ไม่นับเป็นหัวข้อ แม้จะขึ้นต้นด้วย # ก็ตาม
    เพราะคอมเมนต์ของ Python, Bash, Ruby, YAML หน้าตาเหมือนหัวข้อ markdown เป๊ะ
    ถ้าไม่กันไว้ ตัวอย่างโค้ดจะถูกผ่าครึ่งตรงกลาง แล้วคอมเมนต์กลายเป็นชื่อหัวข้อ
    ของ chunk — ทั้งโค้ดที่ขาดและหัวข้อที่ผิดล้วนทำให้ retrieval หาไม่เจอ
    """
    blocks: list[tuple[str | None, str]] = []
    heading: str | None = None
    buffer: list[str] = []
    in_code = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            blocks.append((heading, body))
        buffer.clear()

    for line in text.splitlines():
        if _CODE_FENCE.match(line):
            in_code = not in_code
            buffer.append(line)
            continue

        match = None if in_code else _HEADING.match(line)
        if match:
            flush()
            heading = match.group(2)
        else:
            buffer.append(line)
    flush()

    return blocks or ([(None, text.strip())] if text.strip() else [])


def chunk_page(
    page: PageText,
    *,
    ordinal_start: int = 0,
    size: int | None = None,
    overlap: int | None = None,
    doc_title: str | None = None,
) -> list[TextChunk]:
    size = size or settings.chunk_size
    overlap = overlap if overlap is not None else settings.chunk_overlap

    chunks: list[TextChunk] = []
    ordinal = ordinal_start

    for heading, body in _blocks_with_headings(page.text):
        pieces: list[str] = []
        for paragraph in re.split(r"\n\s*\n", body):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if len(paragraph) <= size:
                pieces.append(paragraph)
            else:
                pieces.extend(split_sentences(paragraph))

        for piece in _pack(pieces, size, overlap):
            # แนบบริบทหัวเอกสาร/หัวข้อไว้ต้น chunk — ช่วย recall ชัดเจน เพราะ chunk
            # กลางเอกสารมักไม่มีคำที่บอกว่ากำลังพูดถึงเรื่องอะไร
            prefix_parts = [p for p in (doc_title, heading) if p]
            text = f"[{' · '.join(prefix_parts)}]\n{piece}" if prefix_parts else piece

            chunks.append(
                TextChunk(
                    ordinal=ordinal,
                    text=text,
                    page_no=page.page_no,
                    source=page.source,
                    heading=heading,
                )
            )
            ordinal += 1

    return chunks


def chunk_document(
    pages: list[PageText],
    *,
    doc_title: str | None = None,
    size: int | None = None,
    overlap: int | None = None,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page in pages:
        chunks.extend(
            chunk_page(
                page,
                ordinal_start=len(chunks),
                size=size,
                overlap=overlap,
                doc_title=doc_title,
            )
        )
    return chunks
