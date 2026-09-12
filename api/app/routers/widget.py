"""ตั้งค่าหน้าตาของ chat widget

endpoint นี้ไม่ต้องล็อกอินโดยตั้งใจ — มันคืนแค่ค่าการแสดงผล ไม่มีข้อมูลเอกสาร
เพื่อให้ widget วาดหน้าตาได้ก่อนที่ผู้ใช้จะเริ่มคุย
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/api/widget", tags=["widget"])


class WidgetConfig(BaseModel):
    title: str
    greeting: str
    placeholder: str
    accent_color: str
    suggestions: list[str]
    # ให้ widget รู้ว่าต้องแนบ cookie ไปด้วยไหม และ endpoint อยู่ที่ไหน
    api_base: str


@router.get("/config", response_model=WidgetConfig)
async def widget_config() -> WidgetConfig:
    return WidgetConfig(
        title=settings.widget_title,
        greeting=settings.widget_greeting,
        placeholder="พิมพ์คำถาม…",
        accent_color=settings.widget_accent_color,
        suggestions=[s.strip() for s in settings.widget_suggestions.split("|") if s.strip()],
        api_base=settings.public_api_url,
    )
