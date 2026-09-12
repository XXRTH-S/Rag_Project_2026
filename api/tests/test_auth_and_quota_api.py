from httpx import AsyncClient

from app.core.config import settings
from app.core.deps import COOKIE_NAME
from app.models.user import User
from tests.conftest import TEST_PASSWORD


async def _login(client: AsyncClient, user: User) -> str:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_login_sets_httponly_cookie(client: AsyncClient, user: User) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200

    cookie = resp.cookies.get(COOKIE_NAME)
    assert cookie
    # cookie ต้องเป็น httponly ไม่งั้น XSS ขโมย token ได้
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


async def test_login_rejects_wrong_password(client: AsyncClient, user: User) -> None:
    resp = await client.post("/api/auth/login", json={"email": user.email, "password": "nope"})
    assert resp.status_code == 401


async def test_login_does_not_leak_which_emails_exist(client: AsyncClient, user: User) -> None:
    unknown = await client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "nope"}
    )
    wrong_pw = await client.post(
        "/api/auth/login", json={"email": user.email, "password": "nope"}
    )
    assert unknown.status_code == wrong_pw.status_code == 401
    assert unknown.json()["detail"] == wrong_pw.json()["detail"]


async def test_me_requires_authentication(client: AsyncClient) -> None:
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_accepts_bearer_token(client: AsyncClient, user: User) -> None:
    token = await _login(client, user)
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == user.email
    assert "password_hash" not in resp.json()


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


async def test_quota_endpoint_works_for_brand_new_user(
    client: AsyncClient, user: User
) -> None:
    """user ที่ยังไม่เคยอัปโหลดคือเคสแรกสุดที่ทุกคนจะเจอ"""
    token = await _login(client, user)
    resp = await client.get("/api/me/quota", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["documents"] == {
        "used": 0,
        "limit": settings.user_daily_document_limit,
        "remaining": settings.user_daily_document_limit,
    }
    assert body["pages"]["remaining"] == settings.user_daily_page_limit
    assert body["unlimited"] is False
    assert body["resets_at"]


async def test_quota_endpoint_reports_admin_as_unlimited(
    client: AsyncClient, admin: User
) -> None:
    token = await _login(client, admin)
    resp = await client.get("/api/me/quota", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["unlimited"] is True
    assert body["documents"]["limit"] is None
    assert body["pages"]["remaining"] is None


async def test_quota_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/me/quota")).status_code == 401
