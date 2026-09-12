"""แปลงหน้า PDF เป็นภาพก่อนส่งเข้า OCR

ใช้ pdftoppm จาก poppler-utils ที่ติดตั้งไว้ใน image แล้ว
เรนเดอร์ทีละหน้าตามที่ต้องการ ไม่ใช่ทั้งไฟล์ — หน้าที่มี text layer อยู่แล้ว
ไม่ต้องเรนเดอร์เลย ซึ่งเป็นที่มาของการประหยัดเวลาส่วนใหญ่
"""
import subprocess
import tempfile
from pathlib import Path

# 200 dpi พอสำหรับ OCR เอกสารทั่วไป สูงกว่านี้ทำให้ภาพใหญ่ขึ้นโดยความแม่นไม่เพิ่ม
# และกิน VRAM ของ vision encoder มากขึ้นด้วย ซึ่งบน 6GB มีผลจริง
DEFAULT_DPI = 200


class RenderError(RuntimeError):
    pass


def render_pdf_page(pdf_path: Path, page_no: int, *, dpi: int = DEFAULT_DPI) -> bytes:
    """คืน PNG ของหน้าที่ระบุ (page_no นับจาก 1)"""
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        result = subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(page_no),
                "-l",
                str(page_no),
                str(pdf_path),
                str(prefix),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RenderError(
                f"pdftoppm ล้มเหลวที่หน้า {page_no}: {result.stderr.decode(errors='ignore')[:200]}"
            )

        images = sorted(Path(tmp).glob("page*.png"))
        if not images:
            raise RenderError(f"pdftoppm ไม่ได้สร้างภาพจากหน้า {page_no}")
        return images[0].read_bytes()
