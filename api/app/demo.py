"""Explicitly provision five synthetic demo identities. Never reconcile passwords on startup."""

import os
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User

DEMO_NAMESPACE = uuid.UUID("b2f64a1d-c674-4305-88ab-5a35ec579841")
DEMO_COLLECTION = "demo-fixtures-v1"


def demo_id(index: int) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, f"user-{index}")


@dataclass(repr=False)
class DemoCredential:
    index: int
    email: str
    password: str


def credentials() -> list[DemoCredential]:
    result = []
    for index in range(1, 6):
        email = os.environ.get(f"DEMO_USER_{index}_EMAIL", "").strip().lower()
        password = os.environ.get(f"DEMO_USER_{index}_PASSWORD", "")
        if email != f"demo{index:02}@example.com":
            raise ValueError(f"DEMO_USER_{index}_EMAIL must use the reserved example.com identity")
        if not 20 <= len(password.encode()) <= 72:
            raise ValueError(f"DEMO_USER_{index}_PASSWORD must contain 20-72 bytes")
        result.append(DemoCredential(index, email, password))
    if len({c.password for c in result}) != 5:
        raise ValueError("Demo passwords must be distinct")
    return result


async def seed_users(session: AsyncSession, items: list[DemoCredential]) -> dict[str, int]:
    if sorted(c.index for c in items) != list(range(1, 6)):
        raise ValueError("Exactly five demo identities are required")
    await session.execute(text("SELECT pg_advisory_xact_lock(2026091301)"))
    pending = []
    for item in items:
        rows = (
            (
                await session.execute(
                    select(User).where(
                        or_(User.id == demo_id(item.index), User.email == item.email)
                    )
                )
            )
            .scalars()
            .all()
        )
        if rows:
            if (
                len(rows) != 1
                or rows[0].id != demo_id(item.index)
                or rows[0].email != item.email
                or rows[0].role != "user"
            ):
                raise ValueError(
                    f"Existing account collision for demo index {item.index}; no account changed"
                )
            continue
        pending.append(
            User(
                id=demo_id(item.index),
                email=item.email,
                password_hash=hash_password(item.password),
                role="user",
                is_active=True,
            )
        )
    session.add_all(pending)
    await session.flush()
    return {"created": len(pending), "unchanged": len(items) - len(pending)}
