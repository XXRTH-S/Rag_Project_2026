"""เทสวงจรชีวิตของ prompt config

บั๊กที่เจอตอนทดสอบเว็บ: เปิดใช้ config แล้วปิดไม่ได้เลย มีแต่ activate
admin ที่ทดลองปรับ prompt จึงเปลี่ยนพฤติกรรมทั้งระบบถาวรโดยไม่มีทางย้อนกลับ
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.prompts import DEFAULT_SYSTEM_PROMPT
from app.models.chat import ChatMessage, ChatSession, PromptConfig
from app.models.user import User
from tests.conftest import TEST_PASSWORD


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create(client: AsyncClient, headers: dict[str, str], name: str = "v1") -> dict:
    resp = await client.post(
        "/api/admin/prompt-configs",
        headers=headers,
        json={"name": name, "system_prompt": "ตอบสั้น ๆ"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_deactivate_returns_to_the_built_in_prompt(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    headers = await _auth(client, admin)
    config = await _create(client, headers)
    await client.post(f"/api/admin/prompt-configs/{config['id']}/activate", headers=headers)

    resp = await client.post(
        f"/api/admin/prompt-configs/{config['id']}/deactivate", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    active = (
        await session.execute(select(PromptConfig).where(PromptConfig.is_active))
    ).scalar_one_or_none()
    assert active is None, "ต้องไม่มี config ไหนใช้งานอยู่ = กลับไปใช้ prompt เริ่มต้น"


async def test_deactivate_is_idempotent(client: AsyncClient, admin: User) -> None:
    headers = await _auth(client, admin)
    config = await _create(client, headers)
    # ยังไม่เคยเปิดใช้เลย สั่งปิดก็ต้องไม่พัง
    resp = await client.post(
        f"/api/admin/prompt-configs/{config['id']}/deactivate", headers=headers
    )
    assert resp.status_code == 200


async def test_delete_removes_the_config(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    headers = await _auth(client, admin)
    config = await _create(client, headers)

    resp = await client.delete(f"/api/admin/prompt-configs/{config['id']}", headers=headers)
    assert resp.status_code == 204

    count = await session.execute(select(func.count()).select_from(PromptConfig))
    assert count.scalar_one() == 0


async def test_deleting_an_active_config_falls_back_to_default(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    headers = await _auth(client, admin)
    config = await _create(client, headers)
    await client.post(f"/api/admin/prompt-configs/{config['id']}/activate", headers=headers)

    await client.delete(f"/api/admin/prompt-configs/{config['id']}", headers=headers)

    active = (
        await session.execute(select(PromptConfig).where(PromptConfig.is_active))
    ).scalar_one_or_none()
    assert active is None


async def test_deleting_a_config_keeps_chat_history(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """ประวัติแชทต้องไม่หายตาม เพราะ FK เป็น ON DELETE SET NULL"""
    headers = await _auth(client, admin)
    config = await _create(client, headers)

    chat_session = ChatSession(id=uuid.uuid4(), channel="playground", user_id=admin.id)
    session.add(chat_session)
    await session.flush()
    message = ChatMessage(
        session_id=chat_session.id,
        role="assistant",
        content="คำตอบเก่า",
        prompt_config_id=uuid.UUID(config["id"]),
    )
    session.add(message)
    await session.commit()

    await client.delete(f"/api/admin/prompt-configs/{config['id']}", headers=headers)

    await session.refresh(message)
    assert message.content == "คำตอบเก่า"
    assert message.prompt_config_id is None


async def test_default_prompt_endpoint_still_serves_the_built_in(
    client: AsyncClient, admin: User
) -> None:
    """หลังปิด config แล้ว หน้าเว็บต้องดึง prompt เริ่มต้นกลับมาแสดงได้"""
    headers = await _auth(client, admin)
    resp = await client.get("/api/admin/prompt-configs/default", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["system_prompt"] == DEFAULT_SYSTEM_PROMPT


async def test_delete_and_deactivate_are_admin_only(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    fake = uuid.uuid4()
    assert (
        await client.post(f"/api/admin/prompt-configs/{fake}/deactivate", headers=headers)
    ).status_code == 403
    assert (
        await client.delete(f"/api/admin/prompt-configs/{fake}", headers=headers)
    ).status_code == 403


async def test_missing_config_returns_404(client: AsyncClient, admin: User) -> None:
    headers = await _auth(client, admin)
    fake = uuid.uuid4()
    assert (
        await client.post(f"/api/admin/prompt-configs/{fake}/deactivate", headers=headers)
    ).status_code == 404
    assert (
        await client.delete(f"/api/admin/prompt-configs/{fake}", headers=headers)
    ).status_code == 404
