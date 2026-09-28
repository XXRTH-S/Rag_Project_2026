"""ผูก retrieval + LLM + การบันทึกประวัติเข้าด้วยกัน

จุดที่สำคัญที่สุด: ถ้า retrieval ไม่มี chunk ไหนผ่าน min_score ให้ตอบว่าไม่พบข้อมูล
**โดยไม่เรียก LLM เลย** — ประหยัดเวลาบนการ์ดช้า และตัดโอกาส hallucinate ทิ้งทั้งหมด
ซึ่งสำคัญเป็นพิเศษกับโมเดล 4B
"""
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.chain import ChatChain
from app.llm.prompts import (
    NO_CONTEXT_ANSWER,
    build_messages,
    excerpt_fallback,
    looks_like_refusal,
)
from app.models.chat import ChatMessage, ChatSession, MessageCitation, PromptConfig
from app.retrieval.embeddings import EmbeddingClient
from app.retrieval.search import SearchHit, search

log = logging.getLogger("app.llm")

HISTORY_TURNS = 4


@dataclass
class AnswerResult:
    answer: str
    hits: list[SearchHit] = field(default_factory=list)
    answered_from_context: bool = True
    latency_ms: int = 0
    message_id: uuid.UUID | None = None


async def _active_prompt_config(session: AsyncSession) -> PromptConfig | None:
    result = await session.execute(select(PromptConfig).where(PromptConfig.is_active))
    return result.scalar_one_or_none()


async def _recent_history(session: AsyncSession, session_id: uuid.UUID) -> list[dict[str, str]]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_TURNS * 2)
    )
    messages = list(reversed(result.scalars().all()))
    return [{"role": m.role, "content": m.content} for m in messages if m.role in ("user", "assistant")]


async def retrieve(
    session: AsyncSession,
    question: str,
    *,
    owner_id: uuid.UUID | None,
    collection: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    hybrid: bool | None = None,
) -> list[SearchHit]:
    vector = await EmbeddingClient().embed_one(question)
    return await search(
        session,
        vector,
        # ส่งคำถามดิบไปด้วยเพื่อให้ keyword leg ของ hybrid ใช้งานได้
        question=question,
        owner_id=owner_id,
        collection=collection,
        top_k=top_k,
        min_score=min_score,
        hybrid=hybrid,
    )


class SessionNotOwned(Exception):
    """ขอต่อบทสนทนาที่มีอยู่จริง แต่ไม่ใช่ของผู้เรียก

    router ต้องแปลงเป็น 404 ไม่ใช่ 403 — 403 เท่ากับยืนยันว่า id นี้มีอยู่จริง
    ซึ่งทำให้ไล่เดาได้ว่าใครคุยอะไรไว้บ้าง
    """


async def ensure_session(
    session: AsyncSession,
    session_id: uuid.UUID | None,
    *,
    channel: str,
    user_id: uuid.UUID | None,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> ChatSession:
    if session_id is not None:
        existing = await session.get(ChatSession, session_id)
        if existing is not None:
            # ตรวจเจ้าของ session ก่อนอ่านประวัติหรือเพิ่มข้อความ แม้จะรู้ session ID ก็ตาม
            if existing.user_id != user_id:
                raise SessionNotOwned
            return existing

    chat_session = ChatSession(
        id=session_id or uuid.uuid4(),
        channel=channel,
        user_id=user_id,
        user_agent=(user_agent or "")[:512] or None,
        client_ip=client_ip,
    )
    session.add(chat_session)
    await session.flush()
    return chat_session


# หัวข้อยาวกว่านี้ก็ล้นแถบข้างอยู่ดี · ตรงกับความยาวของคอลัมน์ใน migration 0005
TITLE_MAX_CHARS = 120

# คำทักทายและคำลองระบบ — ข้อความที่มีแค่คำพวกนี้ไม่บอกว่าคุยเรื่องอะไร
# บทสนทนาที่ขึ้นต้นแบบนี้ให้รอคำถามจริงของผู้ใช้แทน
_GREETINGS = {
    "hi", "hello", "hey", "test", "testing", "ping", "ok",
    "สวัสดี", "สวัสดีครับ", "สวัสดีค่ะ", "หวัดดี", "ทดสอบ", "ทดลอง",
}


def derive_title(question: str) -> str | None:
    """หัวข้อของบทสนทนาจากคำถามแรก · คืน None เมื่อยังตั้งหัวข้อไม่ได้

    คืน None เมื่อเป็นคำทักทายล้วน ๆ เพื่อให้คำถามถัดไปได้ตั้งหัวข้อแทน —
    แถบข้างที่เต็มไปด้วย "hi" ซ้ำ ๆ ไม่ช่วยให้ใครหาบทสนทนาเก่าเจอ

    ตัดตามขอบคำด้วยตัวตัดคำไทย ไม่ใช่ตัดที่ตัวอักษรที่ N ตรง ๆ
    ภาษาไทยไม่มีช่องว่างคั่นคำ การตัดดิบ ๆ จึงได้คำที่ขาดครึ่ง
    """
    text = " ".join(question.split())
    if not text:
        return None
    if text.strip("?!.· ").casefold() in _GREETINGS:
        return None
    if len(text) <= TITLE_MAX_CHARS:
        return text

    try:
        from pythainlp.tokenize import word_tokenize

        pieces = word_tokenize(text, keep_whitespace=True)
    except Exception:  # noqa: BLE001
        # ตัวตัดคำใช้ไม่ได้ก็ยังต้องได้หัวข้อ แค่อาจตัดกลางคำ
        return text[:TITLE_MAX_CHARS].rstrip() + "…"

    out = ""
    for piece in pieces:
        if len(out) + len(piece) > TITLE_MAX_CHARS - 1:
            break
        out += piece
    return (out.rstrip() or text[: TITLE_MAX_CHARS - 1].rstrip()) + "…"


async def _record(
    session: AsyncSession,
    chat_session: ChatSession,
    *,
    question: str,
    answer: str,
    hits: list[SearchHit],
    answered_from_context: bool,
    latency_ms: int,
    model: str | None,
    prompt_config_id: uuid.UUID | None,
    usage: dict | None = None,
) -> uuid.UUID:
    session.add(ChatMessage(session_id=chat_session.id, role="user", content=question))

    # ตั้งหัวข้อครั้งเดียวจากคำถามแรกที่ไม่ใช่คำทักทาย
    if chat_session.title is None:
        chat_session.title = derive_title(question)

    usage = usage or {}
    assistant = ChatMessage(
        session_id=chat_session.id,
        role="assistant",
        content=answer,
        latency_ms=latency_ms,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        model=model,
        prompt_config_id=prompt_config_id,
        answered_from_context=answered_from_context,
    )
    session.add(assistant)
    await session.flush()

    for hit in hits:
        session.add(
            MessageCitation(
                message_id=assistant.id,
                chunk_id=hit.chunk_id,
                # เก็บชื่อ/หน้าไว้ตอนนี้เลย เพราะตอนอ่านประวัติภายหลัง
                # chunk อาจถูกลบไปแล้วจากการ reprocess เอกสาร
                document_id=hit.document_id,
                document_name=hit.document_name,
                page_no=hit.page_no,
                score=hit.score,
                rank=hit.rank,
            )
        )

    await session.commit()
    return assistant.id


async def answer_question(
    session: AsyncSession,
    chat_session: ChatSession,
    question: str,
    *,
    owner_id: uuid.UUID | None,
    collection: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    system_prompt: str | None = None,
    enable_thinking: bool | None = None,
    temperature: float | None = None,
    hits: list[SearchHit] | None = None,
) -> AnswerResult:
    """ตอบคำถามแบบไม่สตรีม

    ส่ง `hits` เข้ามาได้ถ้าผู้เรียกค้นไว้แล้ว — ไม่งั้นจะค้นซ้ำอีกรอบ
    ซึ่งนอกจากเสียเวลา embedding สองเท่าแล้ว ยังทำให้ chunk ที่ผู้เรียกเห็น
    อาจไม่ใช่ชุดเดียวกับที่ส่งให้ LLM จริง
    """
    started = time.perf_counter()

    config = await _active_prompt_config(session)
    if config is not None:
        top_k = top_k if top_k is not None else config.top_k
        min_score = min_score if min_score is not None else config.min_score
        system_prompt = system_prompt or config.system_prompt
        temperature = temperature if temperature is not None else config.temperature
        enable_thinking = enable_thinking if enable_thinking is not None else config.enable_thinking

    if hits is None:
        hits = await retrieve(
            session,
            question,
            owner_id=owner_id,
            collection=collection,
            top_k=top_k,
            min_score=min_score,
        )

    if not hits:
        latency = int((time.perf_counter() - started) * 1000)
        message_id = await _record(
            session,
            chat_session,
            question=question,
            answer=NO_CONTEXT_ANSWER,
            hits=[],
            answered_from_context=False,
            latency_ms=latency,
            model=None,
            prompt_config_id=config.id if config else None,
        )
        return AnswerResult(
            answer=NO_CONTEXT_ANSWER,
            hits=[],
            answered_from_context=False,
            latency_ms=latency,
            message_id=message_id,
        )

    history = await _recent_history(session, chat_session.id)
    messages = build_messages(question, hits, system_prompt=system_prompt, history=history)

    client = ChatChain()
    usage: dict | None = None
    try:
        response = await client.complete(
            messages, temperature=temperature, enable_thinking=enable_thinking
        )
        answer = (response["choices"][0]["message"]["content"] or "").strip()
        usage = response.get("usage")
    except httpx.HTTPError as exc:
        if not settings.llm_fallback_to_excerpts:
            raise
        # ใช้ข้อความจากเอกสารแทนเมื่อ LLM ล้มเหลว เช่นเดียวกับเส้นทาง streaming
        log.warning("เรียก LLM ไม่สำเร็จ ใช้ข้อความจากเอกสารแทน: %s", exc)
        answer = excerpt_fallback(hits)

    latency = int((time.perf_counter() - started) * 1000)
    grounded = not looks_like_refusal(answer)

    message_id = await _record(
        session,
        chat_session,
        question=question,
        answer=answer,
        hits=hits,
        answered_from_context=grounded,
        latency_ms=latency,
        # บันทึกโมเดลที่ตอบจริง ไม่ใช่ตัวที่ตั้งไว้ — อาจเป็นตัวสำรองก็ได้
        model=client.model_used,
        prompt_config_id=config.id if config else None,
        usage=usage,
    )

    return AnswerResult(
        answer=answer,
        hits=hits,
        answered_from_context=grounded,
        latency_ms=latency,
        message_id=message_id,
    )


async def stream_answer(
    session: AsyncSession,
    chat_session: ChatSession,
    question: str,
    *,
    owner_id: uuid.UUID | None,
    collection: str | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """yield (event_name, payload) ให้ router ห่อเป็น SSE"""
    started = time.perf_counter()
    config = await _active_prompt_config(session)

    hits = await retrieve(
        session,
        question,
        owner_id=owner_id,
        collection=collection,
        top_k=config.top_k if config else None,
        min_score=config.min_score if config else None,
    )

    yield (
        "citations",
        {
            "citations": [
                {
                    "rank": h.rank,
                    "document_id": str(h.document_id),
                    "document_name": h.document_name,
                    "page_no": h.page_no,
                    "score": round(h.score, 4),
                }
                for h in hits
            ]
        },
    )

    if not hits:
        latency = int((time.perf_counter() - started) * 1000)
        message_id = await _record(
            session,
            chat_session,
            question=question,
            answer=NO_CONTEXT_ANSWER,
            hits=[],
            answered_from_context=False,
            latency_ms=latency,
            model=None,
            prompt_config_id=config.id if config else None,
        )
        yield ("token", {"text": NO_CONTEXT_ANSWER})
        yield (
            "done",
            {
                "message_id": str(message_id),
                "answered_from_context": False,
                "latency_ms": latency,
            },
        )
        return

    history = await _recent_history(session, chat_session.id)
    messages = build_messages(
        question,
        hits,
        system_prompt=config.system_prompt if config else None,
        history=history,
    )

    parts: list[str] = []
    client = ChatChain()
    model_used: str | None = None

    try:
        async for delta in client.stream(
            messages,
            temperature=config.temperature if config else None,
            enable_thinking=config.enable_thinking if config else None,
        ):
            parts.append(delta)
            yield ("token", {"text": delta})
        model_used = client.model_used
    except httpx.HTTPError as exc:
        if not settings.llm_fallback_to_excerpts:
            raise
        # หาก LLM ล้มเหลว ให้คืนข้อความจากเอกสารที่ค้นพบ
        log.warning("เรียก LLM ไม่สำเร็จ ใช้ข้อความจากเอกสารแทน: %s", exc)
        fallback = excerpt_fallback(hits)
        parts = [fallback]
        model_used = None
        yield ("token", {"text": fallback})

    answer = "".join(parts).strip()
    latency = int((time.perf_counter() - started) * 1000)
    # โมเดลอาจปฏิเสธเองแม้ retrieval หา chunk เจอ ต้องนับเป็นช่องว่างของคลังด้วย
    grounded = not looks_like_refusal(answer)
    message_id = await _record(
        session,
        chat_session,
        question=question,
        answer=answer,
        hits=hits,
        answered_from_context=grounded,
        latency_ms=latency,
        model=model_used,
        prompt_config_id=config.id if config else None,
    )
    yield (
        "done",
        {"message_id": str(message_id), "answered_from_context": grounded, "latency_ms": latency},
    )
