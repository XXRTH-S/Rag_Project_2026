"""เทสการจัดการผู้ใช้

บั๊กที่เจอตอนทดสอบเว็บ: ระบบสร้างบัญชี role "user" ไม่ได้เลย มีแค่ admin จาก .env
ระบบโควตาซึ่งเป็น requirement หลักจึงเข้าไม่ถึงในการใช้งานจริง
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.conftest import TEST_PASSWORD

NEW_PASSWORD = "a-strong-password"


async def _auth(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_admin_can_create_a_user_who_can_log_in(
    client: AsyncClient, admin: User
) -> None:
    """เคสหลักที่เคยทำไม่ได้เลย"""
    headers = await _auth(client, admin)
    resp = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"email": "somchai@example.com", "password": NEW_PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "user"

    login = await client.post(
        "/api/auth/login", json={"email": "somchai@example.com", "password": NEW_PASSWORD}
    )
    assert login.status_code == 200


async def test_created_user_gets_a_real_quota(client: AsyncClient, admin: User) -> None:
    """admin เป็น unlimited โควตาจึงทดสอบไม่ได้จนกว่าจะมี user จริง"""
    headers = await _auth(client, admin)
    await client.post(
        "/api/admin/users",
        headers=headers,
        json={"email": "somsri@example.com", "password": NEW_PASSWORD},
    )

    login = await client.post(
        "/api/auth/login", json={"email": "somsri@example.com", "password": NEW_PASSWORD}
    )
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    quota = (await client.get("/api/me/quota", headers=user_headers)).json()

    assert quota["unlimited"] is False
    assert quota["documents"]["limit"] == 5
    assert quota["pages"]["limit"] == 500


async def test_email_is_normalised_and_duplicates_rejected(
    client: AsyncClient, admin: User
) -> None:
    headers = await _auth(client, admin)
    first = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"email": "  Somchai@Example.COM  ", "password": NEW_PASSWORD},
    )
    assert first.status_code == 201
    assert first.json()["email"] == "somchai@example.com"

    dup = await client.post(
        "/api/admin/users",
        headers=headers,
        json={"email": "somchai@example.com", "password": NEW_PASSWORD},
    )
    assert dup.status_code == 409


async def test_short_passwords_are_rejected(client: AsyncClient, admin: User) -> None:
    headers = await _auth(client, admin)
    resp = await client.post(
        "/api/admin/users", headers=headers, json={"email": "a@b.com", "password": "123"}
    )
    assert resp.status_code == 422


async def test_list_shows_todays_usage(client: AsyncClient, admin: User, user: User) -> None:
    headers = await _auth(client, admin)
    rows = (await client.get("/api/admin/users", headers=headers)).json()

    by_email = {r["email"]: r for r in rows}
    assert by_email[admin.email]["quota_unlimited"] is True
    assert by_email[user.email]["quota_unlimited"] is False
    assert by_email[user.email]["documents_today"] == 0


async def test_admin_can_reset_a_password(client: AsyncClient, admin: User, user: User) -> None:
    headers = await _auth(client, admin)
    resp = await client.patch(
        f"/api/admin/users/{user.id}", headers=headers, json={"password": NEW_PASSWORD}
    )
    assert resp.status_code == 200

    login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": NEW_PASSWORD}
    )
    assert login.status_code == 200


async def test_deactivated_user_cannot_log_in(
    client: AsyncClient, admin: User, user: User
) -> None:
    headers = await _auth(client, admin)
    await client.patch(f"/api/admin/users/{user.id}", headers=headers, json={"is_active": False})

    login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 403


async def test_admin_cannot_lock_themselves_out(client: AsyncClient, admin: User) -> None:
    """ปิดบัญชีตัวเองหรือลดสิทธิ์ตัวเอง = เข้าระบบไม่ได้อีกเลย"""
    headers = await _auth(client, admin)

    assert (
        await client.patch(f"/api/admin/users/{admin.id}", headers=headers, json={"is_active": False})
    ).status_code == 400
    assert (
        await client.patch(f"/api/admin/users/{admin.id}", headers=headers, json={"role": "user"})
    ).status_code == 400
    assert (
        await client.delete(f"/api/admin/users/{admin.id}", headers=headers)
    ).status_code == 400


async def test_cannot_remove_the_last_admin(
    client: AsyncClient, session: AsyncSession, admin: User
) -> None:
    """ระบบที่ไม่มี admin ใช้งานได้เลย = กู้คืนได้ทางเดียวคือแก้ .env แล้ว restart"""
    headers = await _auth(client, admin)
    second = (
        await client.post(
            "/api/admin/users",
            headers=headers,
            json={"email": "admin2@example.com", "password": NEW_PASSWORD, "role": "admin"},
        )
    ).json()

    # มี admin สองคนแล้ว ลดสิทธิ์คนที่สองได้
    assert (
        await client.patch(
            f"/api/admin/users/{second['id']}", headers=headers, json={"role": "user"}
        )
    ).status_code == 200

    # เหลือ admin คนเดียว จะลดสิทธิ์อีกไม่ได้ (และเป็นตัวเองด้วย)
    admins = (
        await session.execute(select(User).where(User.role == "admin", User.is_active))
    ).scalars().all()
    assert len(admins) == 1


async def test_deleting_a_user_removes_their_documents(
    client: AsyncClient, session: AsyncSession, admin: User, user: User
) -> None:
    from app.models.document import Document

    document = Document(
        id=uuid.uuid4(),
        owner_id=user.id,
        filename="ของเขา.pdf",
        mime_type="application/pdf",
        storage_path="/data/uploads/x.pdf",
        size_bytes=1,
        page_count=1,
    )
    session.add(document)
    await session.commit()
    # เก็บ id ไว้ก่อน expire — ไม่งั้นการอ่าน attribute จะไปโหลดจาก DB นอก greenlet context
    document_id = document.id

    headers = await _auth(client, admin)
    assert (await client.delete(f"/api/admin/users/{user.id}", headers=headers)).status_code == 204

    # ต้องถาม DB จริง — session.get จะคืน object ที่ค้างอยู่ใน identity map
    session.expire_all()
    remaining = await session.execute(
        select(func.count()).select_from(Document).where(Document.id == document_id)
    )
    assert remaining.scalar_one() == 0


async def test_user_management_is_admin_only(client: AsyncClient, user: User) -> None:
    headers = await _auth(client, user)
    assert (await client.get("/api/admin/users", headers=headers)).status_code == 403
    assert (
        await client.post(
            "/api/admin/users", headers=headers, json={"email": "x@y.com", "password": NEW_PASSWORD}
        )
    ).status_code == 403
