"""แอปต้องบูตได้โดยไม่มีแพ็กเกจฝั่ง ingestion

เหตุผล: bundle ของ Vercel ไม่ได้ติดตั้ง celery, python-magic, pypdf, pillow,
uvicorn และ alembic (ดู api/requirements.txt) ทั้งหมดนี้ถูก import แบบ lazy
อยู่แล้วในฟังก์ชันที่ใช้จริง แต่ไม่มีอะไรบังคับไว้ — ใครเผลอย้าย `import magic`
ขึ้นไปไว้หัวไฟล์ ระบบจะพังตอน deploy ไม่ใช่ตอนรันเทส

เทสนี้ทำให้พังตอนรันเทสแทน

ใช้ subprocess ไม่ใช่การสลับ sys.modules ในโปรเซสเดียวกัน — ลองแบบหลังแล้ว
มันทำให้ `settings` กลายเป็นคนละ object กับที่เทสตัวอื่นถืออยู่ แล้ว monkeypatch
ก็ไม่มีผล · อินเทอร์พรีเตอร์ใหม่ยังตรงกับสิ่งที่เกิดจริงตอน cold start มากกว่า
"""
import subprocess
import sys
import textwrap

import pytest
from httpx import AsyncClient

from app.core.config import settings

# ตรงกับของที่ไม่ได้อยู่ใน api/requirements.txt
ABSENT_ON_VERCEL = ("magic", "pypdf", "PIL", "celery", "kombu", "uvicorn", "uvloop", "alembic")

_BLOCK_AND_IMPORT = textwrap.dedent(
    """
    import sys

    ABSENT = {absent!r}

    class Blocker:
        def find_module(self, name, path=None):
            return self if name.split(".")[0] in ABSENT else None

        def load_module(self, name):
            raise ImportError(name + " ไม่ได้อยู่ใน bundle ของ Vercel")

    sys.meta_path.insert(0, Blocker())

    {body}
    """
)


def _run_isolated(body: str) -> subprocess.CompletedProcess:
    """รันโค้ดในอินเทอร์พรีเตอร์ใหม่ที่แพ็กเกจฝั่ง ingestion ถูกบล็อก"""
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_AND_IMPORT.format(absent=ABSENT_ON_VERCEL, body=body)],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
        # อ่าน returncode เองเพื่อแนบ stderr ไปกับข้อความ assert
        # ไม่งั้นเทสล้มโดยบอกแค่ "คำสั่งคืนค่า 1" ซึ่งตามต่อไม่ได้
        check=False,
    )


def test_app_boots_without_the_ingestion_packages() -> None:
    result = _run_isolated("import app.main; print('ok', len(app.main.app.routes))")

    assert result.returncode == 0, f"บูตไม่ได้เมื่อไม่มีแพ็กเกจฝั่ง ingestion:\n{result.stderr}"
    assert result.stdout.startswith("ok")


def test_the_entrypoint_vercel_uses_also_imports() -> None:
    """api/index.py คือไฟล์ที่ Vercel เรียกจริง ต้องผ่านด้วย ไม่ใช่แค่ app.main"""
    result = _run_isolated(
        textwrap.dedent(
            """
            import asyncio
            import index
            from httpx import ASGITransport, AsyncClient

            async def main():
                async with AsyncClient(
                    transport=ASGITransport(app=index.app), base_url="https://vercel.test"
                ) as c:
                    print((await c.get("/health")).status_code)
                    print((await c.get("/api/auth/me")).status_code)

            asyncio.run(main())
            """
        )
    )

    assert result.returncode == 0, f"index.py import ไม่ผ่าน:\n{result.stderr}"
    assert result.stdout.split() == ["200", "401"]


async def test_upload_says_where_to_go_when_ingestion_is_off(
    client: AsyncClient, monkeypatch
) -> None:
    """ปิด ingestion แล้วต้องตอบ 503 พร้อมบอกทาง ไม่ใช่ 500 หรือรับไฟล์ไว้เฉย ๆ"""
    monkeypatch.setattr(settings, "ingestion_enabled", False)

    resp = await client.post(
        "/api/documents", files={"file": ("a.txt", "เนื้อหา".encode(), "text/plain")}
    )

    assert resp.status_code == 503
    assert "worker" in resp.json()["detail"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/documents/bulk",
        "/api/admin/documents/00000000-0000-0000-0000-000000000000/reprocess",
    ],
)
async def test_admin_ingestion_paths_are_closed_too(
    client: AsyncClient, monkeypatch, path: str
) -> None:
    monkeypatch.setattr(settings, "ingestion_enabled", False)

    resp = await client.post(path)

    # 503 ต้องมาก่อนการตรวจสิทธิ์ — ที่ที่ทำไม่ได้ก็คือทำไม่ได้ ไม่ว่าใครเรียก
    assert resp.status_code == 503


def test_ingestion_is_open_by_default() -> None:
    """ค่าเริ่มต้นต้องไม่ปิด ไม่งั้นเครื่องที่มี worker จริงจะใช้งานไม่ได้"""
    from app.core.config import Settings

    assert Settings(_env_file=None).ingestion_enabled is True
