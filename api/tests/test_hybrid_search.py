"""เทส keyword leg และการรวมอันดับแบบ RRF

ใช้เวกเตอร์ที่กำหนดเองเพื่อคุมอันดับฝั่ง vector ให้แน่นอน แล้วดูว่า keyword
เปลี่ยนอันดับสุดท้ายได้จริงตามที่ออกแบบ
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import EMBEDDING_DIM, Chunk, Document
from app.models.user import User
from app.retrieval.keywords import THAI_STOPWORDS, to_search_text, to_tsquery, tokenize
from app.retrieval.search import hybrid_search, search, vector_search

# ---------- tokenize ----------


def test_thai_is_segmented_into_words() -> None:
    # Postgres ตัดคำไทยเองไม่ได้ ถ้าไม่ตัดก่อนจะได้ token เดียวคือทั้งประโยค
    tokens = tokenize("พนักงานลาพักร้อนได้ปีละสิบวัน")
    assert len(tokens) > 1
    assert any("ลาพักร้อน" in t or "พักร้อน" in t for t in tokens)


def test_stopwords_are_dropped() -> None:
    tokens = tokenize("การเบิกค่าเดินทางของพนักงานที่เป็นไปตามระเบียบ")
    assert not (set(tokens) & THAI_STOPWORDS)


def test_punctuation_and_whitespace_are_dropped() -> None:
    assert tokenize("  ,,,   ") == []


def test_search_text_is_space_separated() -> None:
    text = to_search_text("พนักงานลาป่วย")
    assert " " in text
    assert text == text.strip()


def test_tsquery_uses_or_not_and() -> None:
    # คำถามมักมีคำที่ไม่มีในเอกสารปนมา ถ้าใช้ AND จะไม่เจออะไรเลย
    q = to_tsquery("ลาพักร้อนได้กี่วัน")
    assert "|" in q
    assert "&" not in q


def test_tsquery_is_empty_when_only_stopwords() -> None:
    assert to_tsquery("ที่ และ ของ") == ""


def test_tsquery_strips_operator_characters() -> None:
    # อักขระพวกนี้มีความหมายพิเศษใน tsquery ถ้าไม่ตัดออกจะทำให้ query พัง
    q = to_tsquery("ค่าเดินทาง (2,000 บาท) & ที่พัก!")
    for char in "()&!:*":
        assert char not in q


# ---------- hybrid ----------


def _vector(axis: int, weight: float = 1.0) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[axis] = weight
    vec[axis + 1] = (1.0 - weight**2) ** 0.5
    return vec


async def _seed(
    session: AsyncSession, owner: User, items: list[tuple[str, list[float]]]
) -> Document:
    document = Document(
        id=uuid.uuid4(),
        owner_id=owner.id,
        filename="doc.pdf",
        mime_type="application/pdf",
        storage_path=f"/data/uploads/{uuid.uuid4().hex}.pdf",
        size_bytes=1,
        status="ready",
        page_count=1,
    )
    session.add(document)
    await session.flush()

    for ordinal, (content, vector) in enumerate(items):
        session.add(
            Chunk(
                document_id=document.id,
                owner_id=owner.id,
                ordinal=ordinal,
                text=content,
                page_no=1,
                source="parse",
                embedding=vector,
                search_text=to_search_text(content),
            )
        )
    await session.commit()
    return document


async def test_keyword_match_promotes_a_lower_ranked_chunk(
    session: AsyncSession, user: User
) -> None:
    """chunk ที่ vector จัดไว้อันดับ 2 แต่ตรงคำ ควรขึ้นมาอันดับ 1 หลัง RRF"""
    await _seed(
        session,
        user,
        [
            ("เอกสารทั่วไปเกี่ยวกับสวัสดิการและการทำงาน", _vector(0, 1.0)),
            ("อัตราค่าเบี้ยเลี้ยงเดินทางระดับผู้จัดการ", _vector(0, 0.97)),
        ],
    )
    query = _vector(0, 1.0)

    by_vector = await vector_search(session, query, min_score=-1.0)
    assert by_vector[0].text.startswith("เอกสารทั่วไป")

    fused = await hybrid_search(session, query, "ค่าเบี้ยเลี้ยงผู้จัดการ", min_score=-1.0)
    assert fused[0].text.startswith("อัตราค่าเบี้ยเลี้ยง")
    assert fused[0].keyword_rank == 1
    assert fused[0].vector_rank == 2


async def test_hybrid_reports_both_ranks(session: AsyncSession, user: User) -> None:
    await _seed(session, user, [("ระเบียบการลาพักร้อนของพนักงาน", _vector(0, 1.0))])
    hits = await hybrid_search(session, _vector(0, 1.0), "ลาพักร้อน", min_score=-1.0)

    assert hits[0].vector_rank == 1
    assert hits[0].keyword_rank == 1
    # score ยังเป็น cosine similarity เพื่อให้เทียบข้าม query ได้เหมือนเดิม
    assert 0.99 < hits[0].score <= 1.0


async def test_hybrid_still_applies_min_score(session: AsyncSession, user: User) -> None:
    """keyword ช่วยจัดอันดับได้ แต่ต้องไม่ดัน chunk ที่ความหมายห่างเข้ามา"""
    await _seed(session, user, [("ค่าเบี้ยเลี้ยงเดินทาง", _vector(30, 1.0))])
    hits = await hybrid_search(session, _vector(0, 1.0), "ค่าเบี้ยเลี้ยงเดินทาง", min_score=0.5)
    assert hits == []


async def test_hybrid_falls_back_when_query_has_no_keywords(
    session: AsyncSession, user: User
) -> None:
    await _seed(session, user, [("เนื้อหาบางอย่าง", _vector(0, 1.0))])
    # คำถามที่เหลือแต่ stopword — ต้องไม่พังและต้องยังค้นด้วย vector ได้
    hits = await hybrid_search(session, _vector(0, 1.0), "ที่ และ ของ", min_score=-1.0)
    assert len(hits) == 1


async def test_hybrid_respects_owner_scope(
    session: AsyncSession, user: User, admin: User
) -> None:
    await _seed(session, admin, [("ความลับของคนอื่น", _vector(0, 1.0))])
    hits = await hybrid_search(
        session, _vector(0, 1.0), "ความลับ", owner_id=user.id, min_score=-1.0
    )
    assert hits == []


async def test_search_dispatches_by_flag(session: AsyncSession, user: User) -> None:
    await _seed(
        session,
        user,
        [
            ("เอกสารทั่วไปเกี่ยวกับสวัสดิการ", _vector(0, 1.0)),
            ("อัตราค่าเบี้ยเลี้ยงเดินทาง", _vector(0, 0.97)),
        ],
    )
    query = _vector(0, 1.0)

    plain = await search(session, query, question="ค่าเบี้ยเลี้ยง", hybrid=False, min_score=-1.0)
    fused = await search(session, query, question="ค่าเบี้ยเลี้ยง", hybrid=True, min_score=-1.0)

    assert plain[0].text.startswith("เอกสารทั่วไป")
    assert fused[0].text.startswith("อัตราค่าเบี้ยเลี้ยง")
