"""ค้นคืน chunk — vector อย่างเดียว หรือผสมกับ keyword

จุดสำคัญ:
1. กรองสิทธิ์ที่ระดับ SQL ไม่ใช่กรองหลัง search — ถ้ากรองทีหลัง user จะได้ผลน้อยกว่า
   top_k ที่ขอ หรือแย่กว่านั้นคือเห็น chunk ของคนอื่นถ้าลืมกรอง
2. มี min_score เสมอ — ถ้าไม่มี chunk ไหนผ่านเกณฑ์ ต้องตอบว่า "ไม่พบข้อมูล"
   ห้ามส่ง chunk ที่ไม่เกี่ยวให้ LLM เดา ยิ่งกับโมเดลเล็กที่ hallucinate ง่าย
3. hybrid ใช้ Reciprocal Rank Fusion รวมสองอันดับ ไม่ใช่บวกคะแนนกันตรง ๆ
   เพราะ cosine similarity กับ ts_rank อยู่คนละสเกลและเทียบกันไม่ได้
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Chunk, Document
from app.retrieval.keywords import to_tsquery

# ค่ามาตรฐานของ RRF จากงานต้นฉบับ — ลดอิทธิพลของอันดับต้น ๆ ไม่ให้ครอบงำผลรวม
RRF_K = 60


@dataclass
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    text: str
    page_no: int | None
    source: str
    score: float  # cosine similarity — เทียบข้าม query ได้
    rank: int
    vector_rank: int | None = None
    keyword_rank: int | None = None


def _base_query(
    query_vector: list[float],
    *,
    owner_id: uuid.UUID | None,
    collection: str | None,
) -> Select:
    # cosine_distance อยู่ในช่วง 0..2 ยิ่งน้อยยิ่งใกล้ แปลงเป็น similarity 1..-1
    distance = Chunk.embedding.cosine_distance(query_vector).label("distance")

    stmt = (
        select(Chunk, Document.filename, distance)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.embedding.is_not(None))
        # เอกสารที่ยังประมวลผลไม่เสร็จต้องไม่โผล่มาในคำตอบ
        .where(Document.status == "ready")
        .order_by(distance)
    )

    if owner_id is not None:
        stmt = stmt.where(Chunk.owner_id == owner_id)
    if collection is not None:
        stmt = stmt.where(Document.collection == collection)

    return stmt


async def vector_search(
    session: AsyncSession,
    query_vector: list[float],
    *,
    owner_id: uuid.UUID | None = None,
    collection: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[SearchHit]:
    top_k = top_k or settings.retrieval_top_k
    threshold = settings.retrieval_min_score if min_score is None else min_score

    stmt = _base_query(query_vector, owner_id=owner_id, collection=collection).limit(top_k)
    rows = (await session.execute(stmt)).all()

    hits: list[SearchHit] = []
    for chunk, filename, distance in rows:
        score = 1.0 - float(distance)
        if score < threshold:
            # เรียงตามระยะทางอยู่แล้ว เจอตัวแรกที่ต่ำกว่าเกณฑ์ก็หยุดได้เลย
            break
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_name=filename,
                text=chunk.text,
                page_no=chunk.page_no,
                source=chunk.source,
                score=score,
                rank=len(hits) + 1,
                vector_rank=len(hits) + 1,
            )
        )

    return hits


_HYBRID_SQL = """
WITH filtered AS (
    SELECT c.id, c.document_id, c.text, c.page_no, c.source, c.search_vector,
           d.filename,
           1 - (c.embedding <=> CAST(:qvec AS vector)) AS similarity,
           c.embedding <=> CAST(:qvec AS vector) AS distance
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL
      AND d.status = 'ready'
      AND (CAST(:owner_id AS uuid) IS NULL OR c.owner_id = CAST(:owner_id AS uuid))
      AND (CAST(:collection AS text) IS NULL OR d.collection = CAST(:collection AS text))
),
vec AS (
    SELECT id, row_number() OVER (ORDER BY distance) AS vrank
    FROM filtered
    ORDER BY distance
    LIMIT :candidate_pool
),
kw AS (
    SELECT id,
           row_number() OVER (
               ORDER BY ts_rank_cd(search_vector, to_tsquery('simple', :tsq)) DESC
           ) AS krank
    FROM filtered
    WHERE search_vector @@ to_tsquery('simple', :tsq)
    LIMIT :candidate_pool
),
ids AS (
    SELECT id FROM vec
    UNION
    SELECT id FROM kw
)
SELECT f.id, f.document_id, f.text, f.page_no, f.source, f.filename, f.similarity,
       vec.vrank, kw.krank
FROM ids
JOIN filtered f ON f.id = ids.id
LEFT JOIN vec ON vec.id = ids.id
LEFT JOIN kw ON kw.id = ids.id
"""
# รวม candidate จากทั้ง vector และ keyword
# ผลที่ตรง keyword ใช้ keyword_floor ส่วนผลอื่นใช้ min_score


async def hybrid_search(
    session: AsyncSession,
    query_vector: list[float],
    question: str,
    *,
    owner_id: uuid.UUID | None = None,
    collection: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[SearchHit]:
    """รวมอันดับจาก vector กับ keyword ด้วย RRF

    keyword leg ช่วยเรื่องคำเฉพาะที่ embedding จับไม่ติด เช่น เลขมาตรา ชื่อเฉพาะ
    ตัวย่อ หรือตัวเลข ซึ่งเป็นจุดอ่อนที่รู้กันของ dense retrieval
    """
    top_k = top_k or settings.retrieval_top_k
    threshold = settings.retrieval_min_score if min_score is None else min_score
    tsq = to_tsquery(question)

    if not tsq:
        # คำถามไม่เหลือคำสำคัญเลยหลังตัด stopword — ใช้ vector อย่างเดียว
        return await vector_search(
            session,
            query_vector,
            owner_id=owner_id,
            collection=collection,
            top_k=top_k,
            min_score=min_score,
        )

    rows = (
        await session.execute(
            text(_HYBRID_SQL),
            {
                "qvec": "[" + ",".join(str(v) for v in query_vector) + "]",
                "tsq": tsq,
                "owner_id": str(owner_id) if owner_id else None,
                "collection": collection,
                "candidate_pool": max(top_k * 4, 30),
            },
        )
    ).mappings().all()

    keyword_floor = min(threshold, settings.retrieval_keyword_floor)

    scored = []
    for row in rows:
        similarity = float(row["similarity"])
        matched_keyword = row["krank"] is not None

        # ใช้ keyword_floor เมื่อคำค้นตรง ไม่ว่า vector จะค้นพบ chunk นี้ด้วยหรือไม่
        floor = keyword_floor if matched_keyword else threshold
        if similarity < floor:
            continue

        rrf = 0.0
        if row["vrank"] is not None:
            rrf += 1.0 / (RRF_K + row["vrank"])
        if matched_keyword:
            rrf += 1.0 / (RRF_K + row["krank"])
        scored.append((rrf, similarity, row))

    scored.sort(key=lambda item: (-item[0], -item[1]))

    return [
        SearchHit(
            chunk_id=row["id"],
            document_id=row["document_id"],
            document_name=row["filename"],
            text=row["text"],
            page_no=row["page_no"],
            source=row["source"],
            score=similarity,
            rank=index + 1,
            vector_rank=int(row["vrank"]) if row["vrank"] is not None else None,
            keyword_rank=int(row["krank"]) if row["krank"] is not None else None,
        )
        for index, (_, similarity, row) in enumerate(scored[:top_k])
    ]


async def search(
    session: AsyncSession,
    query_vector: list[float],
    *,
    question: str | None = None,
    owner_id: uuid.UUID | None = None,
    collection: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    hybrid: bool | None = None,
) -> list[SearchHit]:
    use_hybrid = settings.retrieval_hybrid if hybrid is None else hybrid

    if use_hybrid and question:
        return await hybrid_search(
            session,
            query_vector,
            question,
            owner_id=owner_id,
            collection=collection,
            top_k=top_k,
            min_score=min_score,
        )

    return await vector_search(
        session,
        query_vector,
        owner_id=owner_id,
        collection=collection,
        top_k=top_k,
        min_score=min_score,
    )
