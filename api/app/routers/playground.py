"""Playground สำหรับ admin — ทดสอบและปรับจูนก่อนเอาขึ้นใช้จริง

ต่างจาก /api/chat ตรงที่คืน **chunk ดิบพร้อม score** กลับมาด้วย
เพราะเวลาคำตอบผิด ต้องแยกให้ออกว่าเป็นเพราะ retrieval หาไม่เจอ
หรือเจอแล้วแต่โมเดลตอบเพี้ยน — สองอย่างนี้แก้คนละทางกันสิ้นเชิง
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.core.db import get_session
from app.core.deps import require_admin
from app.llm import orchestrator
from app.llm.prompts import DEFAULT_SYSTEM_PROMPT
from app.models.chat import PromptConfig
from app.models.user import User
from app.schemas.base import StrictModel

router = APIRouter(prefix="/api/admin", tags=["playground"])


class PlaygroundQuery(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    collection: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    system_prompt: str | None = None
    enable_thinking: bool | None = None
    # ค่า false ทำให้ทดลอง retrieval ได้เร็ว ๆ โดยไม่ต้องรอ GPU ตอบ
    # ซึ่งบนการ์ดนี้ต่างกันหลายสิบวินาทีต่อครั้ง
    call_llm: bool = True


class PromptConfigIn(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    min_score: float = Field(default=0.35, ge=-1.0, le=1.0)
    enable_thinking: bool = False


class PromptConfigOut(PromptConfigIn):
    id: uuid.UUID
    is_active: bool

    model_config = {"from_attributes": True}


@router.post("/playground/query")
async def playground_query(
    payload: PlaygroundQuery,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # เรียกโมเดลเหมือน /api/chat ทุกประการ ถ้าไม่คุมตรงนี้ เพดานของแชทก็ไร้ความหมาย
    # เพราะยิงทาง playground แทนได้ · การ์ดใบเดียวตอบได้ทีละคำขอ ยิงรัวคือล็อกคิวทุกคน
    await ratelimit.enforce(
        request,
        scope="playground",
        limit=settings.rate_limit_playground_per_minute,
        window_seconds=60,
    )

    hits = await orchestrator.retrieve(
        session,
        payload.message,
        owner_id=None,  # admin เห็นทุกเอกสาร
        collection=payload.collection,
        top_k=payload.top_k,
        min_score=payload.min_score,
    )

    result = {
        "question": payload.message,
        "hits": [
            {
                "rank": h.rank,
                "score": round(h.score, 4),
                "document_id": str(h.document_id),
                "document_name": h.document_name,
                "page_no": h.page_no,
                "source": h.source,
                "text": h.text,
            }
            for h in hits
        ],
        "answer": None,
        "answered_from_context": bool(hits),
    }

    if not payload.call_llm or not hits:
        return result

    chat_session = await orchestrator.ensure_session(
        session, None, channel="playground", user_id=admin.id
    )
    await session.commit()

    answer = await orchestrator.answer_question(
        session,
        chat_session,
        payload.message,
        owner_id=None,
        collection=payload.collection,
        top_k=payload.top_k,
        min_score=payload.min_score,
        system_prompt=payload.system_prompt,
        temperature=payload.temperature,
        enable_thinking=payload.enable_thinking,
        # ส่ง chunk ที่ค้นไว้แล้วเข้าไป ไม่ให้ค้นซ้ำ — นอกจากเสียเวลา embedding สองเท่า
        # ยังทำให้ chunk ที่โชว์ให้ admin ดูอาจไม่ใช่ชุดเดียวกับที่ส่งให้ LLM
        # ซึ่งทำลายจุดประสงค์ของ Playground ที่มีไว้ debug พอดี
        hits=hits,
    )

    result["answer"] = answer.answer
    result["latency_ms"] = answer.latency_ms
    result["message_id"] = str(answer.message_id) if answer.message_id else None
    result["answered_from_context"] = answer.answered_from_context
    return result


@router.get("/prompt-configs", response_model=list[PromptConfigOut])
async def list_prompt_configs(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(PromptConfig).order_by(PromptConfig.created_at))
    return list(result.scalars().all())


@router.get("/prompt-configs/default")
async def default_prompt(_: User = Depends(require_admin)) -> dict:
    return {"system_prompt": DEFAULT_SYSTEM_PROMPT}


@router.post(
    "/prompt-configs", response_model=PromptConfigOut, status_code=status.HTTP_201_CREATED
)
async def create_prompt_config(
    payload: PromptConfigIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    config = PromptConfig(**payload.model_dump(), is_active=False)
    session.add(config)
    await session.commit()
    return config


@router.post("/prompt-configs/{config_id}/deactivate", response_model=PromptConfigOut)
async def deactivate_prompt_config(
    config_id: uuid.UUID,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """กลับไปใช้ prompt เริ่มต้นที่ฝังในโค้ด

    ถ้าไม่มีทางปิด admin ที่ทดลองปรับ prompt จะเปลี่ยนพฤติกรรมทั้งระบบถาวร
    ทางเดียวคือไปสร้าง config ใหม่ที่ก๊อป prompt เดิมมา ซึ่งไม่ควรต้องทำ
    """
    config = await session.get(PromptConfig, config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ prompt config")

    config.is_active = False
    await session.commit()
    return config


@router.delete("/prompt-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt_config(
    config_id: uuid.UUID,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """ลบ config ทิ้ง — ถ้ากำลังใช้งานอยู่ ระบบจะกลับไปใช้ prompt เริ่มต้น

    ประวัติแชทที่อ้างถึง config นี้ไม่หาย เพราะ FK เป็น ON DELETE SET NULL
    """
    config = await session.get(PromptConfig, config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ prompt config")

    await session.delete(config)
    await session.commit()


@router.post("/prompt-configs/{config_id}/activate", response_model=PromptConfigOut)
async def activate_prompt_config(
    config_id: uuid.UUID,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    config = await session.get(PromptConfig, config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบ prompt config")

    # ต้องปิดตัวเดิมก่อนเปิดตัวใหม่ ไม่ใช่ทำพร้อมกัน — DB มี unique index
    # บน (is_active) WHERE is_active ที่บังคับว่ามี active ได้แค่ตัวเดียว
    # ถ้าเปิดตัวใหม่ก่อนจะชน constraint ทันที
    await session.execute(
        update(PromptConfig).where(PromptConfig.is_active).values(is_active=False)
    )
    await session.flush()

    config.is_active = True
    await session.commit()
    return config
