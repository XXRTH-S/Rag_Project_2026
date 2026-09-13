"""เทสการแบ่งหน้าของรายการ

เดิม list endpoint คืน array เปล่า ๆ พร้อม limit ตายตัวที่ 50 แถว ผู้ใช้ที่มี
เอกสารมากกว่านั้นมองไม่เห็นของเก่า **และไม่มีอะไรบอกว่าถูกตัด** ซึ่งแย่กว่า
การเห็นไม่ครบ เพราะเข้าใจผิดว่านั่นคือทั้งหมดที่มี
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.user import User
from tests.conftest import TEST_PASSWORD


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_documents(session: AsyncSession, owner: User, count: int) -> None:
    for i in range(count):
        session.add(
            Document(
                id=uuid.uuid4(),
                owner_id=owner.id,
                filename=f"เอกสาร-{i:03d}.txt",
                mime_type="text/plain",
                storage_path=f"/data/uploads/{uuid.uuid4().hex}.txt",
                size_bytes=10,
                status="ready",
                page_count=1,
            )
        )
    await session.commit()


async def test_response_says_how_many_there_are_in_total(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_documents(session, user, 7)
    headers = await _auth(client, user)

    body = (await client.get("/api/documents?limit=3", headers=headers)).json()
    assert len(body["items"]) == 3
    assert body["total"] == 7, "ต้องบอกจำนวนทั้งหมด ไม่ใช่จำนวนที่ส่งมาในหน้านี้"
    assert body["limit"] == 3
    assert body["offset"] == 0


async def test_offset_walks_through_without_repeating(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    await _seed_documents(session, user, 7)
    headers = await _auth(client, user)

    first = (await client.get("/api/documents?limit=3&offset=0", headers=headers)).json()
    second = (await client.get("/api/documents?limit=3&offset=3", headers=headers)).json()
    third = (await client.get("/api/documents?limit=3&offset=6", headers=headers)).json()

    names = [d["filename"] for page in (first, second, third) for d in page["items"]]
    assert len(names) == 7
    assert len(set(names)) == 7, "หน้าที่ต่อกันต้องไม่ซ้ำและไม่ตกหล่น"


async def test_total_respects_ownership(
    client: AsyncClient, session: AsyncSession, user: User, admin: User
) -> None:
    """total ต้องนับด้วยเงื่อนไขเดียวกับที่ดึง ไม่งั้น user จะเห็นว่ามีอีกเยอะ
    แล้วกดโหลดเพิ่มไปเรื่อย ๆ โดยไม่ได้อะไรกลับมา
    """
    await _seed_documents(session, user, 2)
    await _seed_documents(session, admin, 5)

    as_user = await _auth(client, user)
    body = (await client.get("/api/documents", headers=as_user)).json()
    assert body["total"] == 2, "user ต้องนับเฉพาะเอกสารของตัวเอง"

    as_admin = await _auth(client, admin)
    body = (await client.get("/api/documents", headers=as_admin)).json()
    assert body["total"] == 7, "admin เห็นทุกเอกสาร"


async def test_empty_list_still_has_the_envelope(client: AsyncClient, user: User) -> None:
    """ยังไม่มีเอกสารก็ต้องได้โครงเดิม ไม่ใช่ array เปล่า — ฝั่งเว็บจะได้ไม่ต้องแยกเคส"""
    headers = await _auth(client, user)
    body = (await client.get("/api/documents", headers=headers)).json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


@pytest.mark.parametrize("query", ["limit=0", "limit=999", "offset=-1"])
async def test_out_of_range_paging_is_rejected(
    client: AsyncClient, user: User, query: str
) -> None:
    """กันไม่ให้ดึงทั้งตารางด้วย limit มหาศาล และกัน offset ติดลบที่ทำให้ SQL ล้ม"""
    headers = await _auth(client, user)
    resp = await client.get(f"/api/documents?{query}", headers=headers)
    assert resp.status_code == 422
