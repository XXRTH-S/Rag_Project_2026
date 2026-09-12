"""เทส retrieval ด้วยเวกเตอร์ที่กำหนดเอง

ไม่เรียก embedding model จริง เพราะสิ่งที่ต้องพิสูจน์คือ SQL, การกรองสิทธิ์
และเกณฑ์ min_score ไม่ใช่คุณภาพของโมเดล
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import EMBEDDING_DIM, Chunk, Document
from app.models.user import User
from app.retrieval.search import search


def _vector(*, axis: int, magnitude: float = 1.0) -> list[float]:
    """เวกเตอร์หน่วยที่ชี้ไปแกนเดียว — cosine similarity คำนวณด้วยมือได้"""
    vec = [0.0] * EMBEDDING_DIM
    vec[axis] = magnitude
    return vec


def _mixed_vector(axis_a: int, axis_b: int, weight: float) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[axis_a] = weight
    vec[axis_b] = (1.0 - weight**2) ** 0.5
    return vec


async def _seed_document(
    session: AsyncSession,
    owner: User,
    *,
    filename: str = "doc.pdf",
    status: str = "ready",
    collection: str = "default",
) -> Document:
    document = Document(
        id=uuid.uuid4(),
        owner_id=owner.id,
        filename=filename,
        mime_type="application/pdf",
        storage_path=f"/data/uploads/{uuid.uuid4().hex}.pdf",
        size_bytes=1,
        status=status,
        collection=collection,
        page_count=1,
    )
    session.add(document)
    await session.flush()
    return document


async def _seed_chunk(
    session: AsyncSession,
    document: Document,
    owner: User,
    *,
    ordinal: int,
    text: str,
    vector: list[float],
) -> Chunk:
    chunk = Chunk(
        document_id=document.id,
        owner_id=owner.id,
        ordinal=ordinal,
        text=text,
        page_no=1,
        token_count=len(text),
        source="parse",
        embedding=vector,
    )
    session.add(chunk)
    await session.flush()
    return chunk


async def test_closest_chunk_ranks_first(session: AsyncSession, user: User) -> None:
    doc = await _seed_document(session, user)
    await _seed_chunk(session, doc, user, ordinal=0, text="ตรงเป๊ะ", vector=_vector(axis=0))
    await _seed_chunk(session, doc, user, ordinal=1, text="ใกล้เคียง", vector=_mixed_vector(0, 1, 0.8))
    await _seed_chunk(session, doc, user, ordinal=2, text="คนละเรื่อง", vector=_vector(axis=5))
    await session.commit()

    hits = await search(session, _vector(axis=0), min_score=-1.0)

    assert [h.text for h in hits] == ["ตรงเป๊ะ", "ใกล้เคียง", "คนละเรื่อง"]
    assert [h.rank for h in hits] == [1, 2, 3]
    assert hits[0].score > 0.99
    assert hits[0].document_name == "doc.pdf"


async def test_min_score_cuts_off_irrelevant_chunks(
    session: AsyncSession, user: User
) -> None:
    doc = await _seed_document(session, user)
    await _seed_chunk(session, doc, user, ordinal=0, text="เกี่ยวข้อง", vector=_vector(axis=0))
    await _seed_chunk(session, doc, user, ordinal=1, text="ไม่เกี่ยว", vector=_vector(axis=7))
    await session.commit()

    # แกนตั้งฉากกัน = similarity 0 ซึ่งต่ำกว่าเกณฑ์
    hits = await search(session, _vector(axis=0), min_score=0.35)

    assert [h.text for h in hits] == ["เกี่ยวข้อง"]


async def test_no_relevant_chunk_returns_nothing(session: AsyncSession, user: User) -> None:
    """เคสนี้คือจุดที่ระบบต้องตอบว่า 'ไม่พบข้อมูล' แทนที่จะให้ LLM เดา"""
    doc = await _seed_document(session, user)
    await _seed_chunk(session, doc, user, ordinal=0, text="เรื่องอื่น", vector=_vector(axis=9))
    await session.commit()

    assert await search(session, _vector(axis=0), min_score=0.35) == []


async def test_top_k_limits_results(session: AsyncSession, user: User) -> None:
    doc = await _seed_document(session, user)
    for i in range(6):
        await _seed_chunk(
            session, doc, user, ordinal=i, text=f"chunk {i}", vector=_mixed_vector(0, 1, 0.99 - i * 0.01)
        )
    await session.commit()

    hits = await search(session, _vector(axis=0), top_k=3, min_score=-1.0)
    assert len(hits) == 3


async def test_owner_filter_hides_other_users_chunks(
    session: AsyncSession, user: User, admin: User
) -> None:
    mine = await _seed_document(session, user, filename="mine.pdf")
    theirs = await _seed_document(session, admin, filename="theirs.pdf")
    await _seed_chunk(session, mine, user, ordinal=0, text="ของฉัน", vector=_vector(axis=0))
    await _seed_chunk(session, theirs, admin, ordinal=0, text="ของคนอื่น", vector=_vector(axis=0))
    await session.commit()

    scoped = await search(session, _vector(axis=0), owner_id=user.id, min_score=-1.0)
    assert [h.text for h in scoped] == ["ของฉัน"]

    unscoped = await search(session, _vector(axis=0), min_score=-1.0)
    assert len(unscoped) == 2


async def test_documents_still_processing_are_excluded(
    session: AsyncSession, user: User
) -> None:
    pending = await _seed_document(session, user, filename="wip.pdf", status="processing")
    await _seed_chunk(session, pending, user, ordinal=0, text="ยังไม่เสร็จ", vector=_vector(axis=0))
    await session.commit()

    # chunk ของเอกสารที่ยังประมวลผลไม่เสร็จอาจไม่ครบ ตอบไปจะได้คำตอบที่ขาดบริบท
    assert await search(session, _vector(axis=0), min_score=-1.0) == []


async def test_collection_filter(session: AsyncSession, user: User) -> None:
    hr = await _seed_document(session, user, filename="hr.pdf", collection="hr")
    it = await _seed_document(session, user, filename="it.pdf", collection="it")
    await _seed_chunk(session, hr, user, ordinal=0, text="ระเบียบลา", vector=_vector(axis=0))
    await _seed_chunk(session, it, user, ordinal=0, text="รหัสผ่าน", vector=_vector(axis=0))
    await session.commit()

    hits = await search(session, _vector(axis=0), collection="hr", min_score=-1.0)
    assert [h.text for h in hits] == ["ระเบียบลา"]


async def test_chunks_without_embedding_are_skipped(
    session: AsyncSession, user: User
) -> None:
    doc = await _seed_document(session, user)
    await _seed_chunk(session, doc, user, ordinal=0, text="มีเวกเตอร์", vector=_vector(axis=0))
    session.add(
        Chunk(
            document_id=doc.id,
            owner_id=user.id,
            ordinal=1,
            text="ยังไม่ได้ embed",
            page_no=1,
            source="parse",
            embedding=None,
        )
    )
    await session.commit()

    hits = await search(session, _vector(axis=0), min_score=-1.0)
    assert [h.text for h in hits] == ["มีเวกเตอร์"]
