import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.demo import DemoCredential, demo_id, seed_users
from app.demo_retention import expire_demo
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.user import User


def entries():
    return [
        DemoCredential(i, f"demo{i:02}@example.com", f"test-only-password-{i}-long")
        for i in range(1, 6)
    ]


async def test_seed_is_idempotent_and_preserves_suspension(session):
    assert (await seed_users(session, entries()))["created"] == 5
    await session.commit()
    user = await session.get(User, demo_id(1))
    assert verify_password(entries()[0].password, user.password_hash)
    original = user.password_hash
    user.is_active = False
    await session.commit()
    second = entries()
    second[0].password = "new-password-must-not-overwrite"
    assert (await seed_users(session, second))["created"] == 0
    await session.commit()
    assert user.password_hash == original
    assert user.is_active is False
    assert len((await session.execute(select(User))).scalars().all()) == 5


async def test_collision_creates_no_accounts(session):
    session.add(
        User(
            email=entries()[3].email,
            password_hash=hash_password("existing-account-password"),
            role="user",
        )
    )
    await session.commit()
    with pytest.raises(ValueError, match="collision"):
        await seed_users(session, entries())
    await session.rollback()
    assert len((await session.execute(select(User))).scalars().all()) == 1


async def test_all_demo_accounts_authenticate_and_suspension_blocks_token(client, session):
    await seed_users(session, entries())
    await session.commit()
    for item in entries():
        r = await client.post(
            "/api/auth/login", json={"email": item.email, "password": item.password}
        )
        assert r.status_code == 200
        assert (await client.get("/api/auth/me")).json()["role"] == "user"
    r = await client.post(
        "/api/auth/login", json={"email": entries()[0].email, "password": entries()[0].password}
    )
    token = r.json()["access_token"]
    user = await session.get(User, demo_id(1))
    user.is_active = False
    await session.commit()
    assert (
        await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401


async def test_feedback_cannot_target_another_users_message(client, session):
    await seed_users(session, entries())
    chat = ChatSession(user_id=demo_id(1), channel="widget")
    session.add(chat)
    await session.flush()
    message = ChatMessage(session_id=chat.id, role="assistant", content="Synthetic")
    session.add(message)
    await session.commit()
    item = entries()[1]
    await client.post("/api/auth/login", json={"email": item.email, "password": item.password})
    assert (
        await client.post("/api/feedback", json={"message_id": str(message.id), "rating": 1})
    ).status_code == 404


async def test_retention_deletes_only_old_demo_data(session, user, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    await seed_users(session, entries())
    now = datetime.now(UTC)
    records = []
    for owner, age in [(demo_id(1), 91), (demo_id(2), 1), (user.id, 91)]:
        folder = tmp_path / str(owner)
        folder.mkdir()
        path = folder / "fixture.md"
        path.write_text("synthetic")
        doc = Document(
            id=uuid.uuid4(),
            owner_id=owner,
            filename="fixture.md",
            mime_type="text/markdown",
            storage_path=str(path),
            status="ready",
            created_at=now - timedelta(days=age),
        )
        session.add(doc)
        records.append((doc.id, path))
    await session.commit()
    result = await expire_demo(session, apply=True, now=now)
    assert result["expired_documents"] == 1
    assert not records[0][1].exists()
    for uid, path in records[1:]:
        assert path.exists()
        assert await session.get(Document, uid) is not None
