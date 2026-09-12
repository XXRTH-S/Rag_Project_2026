#!/usr/bin/env python
"""เฟส 0 — พิสูจน์ว่าโมเดลทั้งสองตัวใช้งานได้จริงบน RTX 3050 6GB

รัน:
    .\\dc.ps1 exec api python scripts/spike.py
    .\\dc.ps1 exec api python scripts/spike.py --image /data/uploads/test.png
    .\\dc.ps1 exec api python scripts/spike.py --pdf /data/uploads/scan.pdf --page 1

สิ่งที่ต้องผ่านก่อนไปเฟสถัดไป:
  1. โมเดลทั้งสองตัวอยู่ใน /v1/models
  2. OCR อ่านหน้าเอกสารไทยออกเป็น markdown
  3. ทุกโมเดลขึ้น 100% GPU (ถ้าไม่ใช่ ทุกตัวเลขเวลาที่วัดได้จะไม่มีความหมาย)
  4. เวลาต่อหน้าจริง — เอาไปคำนวณ ETA ของคิวในเฟส 3
"""
import argparse
import asyncio
import mimetypes
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.ingestion.ocr_typhoon import TyphoonOcrClient  # noqa: E402
from app.llm import ollama_admin  # noqa: E402
from app.llm.client import ChatClient  # noqa: E402
from app.retrieval.embeddings import EmbeddingClient  # noqa: E402

OK = "\033[92mOK\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"


def head(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


async def step_models() -> bool:
    head("1. โมเดลที่ endpoint มองเห็น")
    ok = True

    try:
        llm_models = await ChatClient().list_models()
        print(f"  LLM endpoint : {settings.llm_base_url}")
        print(f"  พบโมเดล      : {llm_models or '(ว่าง)'}")
        if settings.llm_model in llm_models:
            print(f"  [{OK}] {settings.llm_model}")
        else:
            print(f"  [{FAIL}] ไม่พบ {settings.llm_model} — ยังไม่ได้ pull")
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"  [{FAIL}] ต่อ LLM endpoint ไม่ได้: {type(exc).__name__}: {exc}")
        ok = False

    try:
        ocr_models = await ChatClient(
            base_url=settings.typhoon_ocr_base_url,
            api_key=settings.typhoon_ocr_api_key,
        ).list_models()
        if settings.typhoon_ocr_model in ocr_models:
            print(f"  [{OK}] {settings.typhoon_ocr_model}")
        else:
            print(f"  [{FAIL}] ไม่พบ {settings.typhoon_ocr_model} — ยังไม่ได้ pull")
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"  [{FAIL}] ต่อ OCR endpoint ไม่ได้: {type(exc).__name__}: {exc}")
        ok = False

    return ok


async def step_gpu() -> None:
    head("2. โมเดลรันบน GPU หรือหล่นไป CPU")
    print(f"  {await ollama_admin.processor_note()}")
    warning = await ollama_admin.warn_if_spilled_to_cpu()
    if warning:
        print(f"  [{WARN}] {warning}")
    else:
        print(f"  [{OK}] ไม่มีโมเดลหล่นไป CPU")


def pdf_page_to_png(pdf_path: Path, page: int) -> Path:
    """ใช้ pdftoppm จาก poppler-utils ที่อยู่ใน image แล้ว"""
    out_dir = Path(tempfile.mkdtemp())
    prefix = out_dir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", "200", "-f", str(page), "-l", str(page), str(pdf_path), str(prefix)],
        check=True,
        capture_output=True,
    )
    pages = sorted(out_dir.glob("page*.png"))
    if not pages:
        raise RuntimeError(f"pdftoppm ไม่ได้สร้างภาพจาก {pdf_path} หน้า {page}")
    return pages[0]


async def step_ocr(image_path: Path) -> None:
    head(f"3. OCR — {image_path.name}")
    image_bytes = image_path.read_bytes()
    mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
    print(f"  ขนาดไฟล์ : {len(image_bytes) / 1024:.0f} KB · task_type={settings.typhoon_ocr_task_type}")
    print("  กำลังส่งเข้า OCR (ครั้งแรกต้องรอ Ollama โหลดโมเดลก่อน)...")

    started = time.perf_counter()
    try:
        result = await TyphoonOcrClient().ocr_image_bytes(image_bytes, mime_type=mime)
    except Exception as exc:  # noqa: BLE001
        print(f"  [{FAIL}] {type(exc).__name__}: {exc}")
        return
    elapsed = time.perf_counter() - started

    print(f"  [{OK}] ใช้เวลา {elapsed:.1f} วินาที · ได้ {len(result.text)} ตัวอักษร")
    if result.completion_tokens:
        print(f"  output {result.completion_tokens} tokens ({result.completion_tokens / elapsed:.1f} tok/s)")
    print("\n  ---- 600 ตัวอักษรแรก ----")
    print("  " + result.text[:600].replace("\n", "\n  "))
    print("  -------------------------")
    print(f"\n  ประมาณการคิว: 500 หน้า = {elapsed * 500 / 3600:.1f} ชั่วโมง")


async def step_chat() -> None:
    head("4. Chat")
    messages = [
        {"role": "system", "content": "ตอบสั้น ๆ เป็นภาษาไทย"},
        {"role": "user", "content": "RAG ย่อมาจากอะไร ตอบสั้น ๆ ไม่เกินสองประโยค"},
    ]
    print("  กำลังยิงคำถาม (ถ้าเพิ่งรัน OCR ไป Ollama ต้องสลับโมเดลก่อน รอ 5-15 วินาที)...")

    started = time.perf_counter()
    try:
        data = await ChatClient().complete(messages)
    except Exception as exc:  # noqa: BLE001
        print(f"  [{FAIL}] {type(exc).__name__}: {exc}")
        return
    elapsed = time.perf_counter() - started

    answer = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    print(f"  [{OK}] ใช้เวลา {elapsed:.1f} วินาที · {usage.get('completion_tokens', '?')} tokens")
    print(f"  ตอบ: {answer.strip()[:400]}")


async def step_embeddings() -> None:
    head("5. Embedding")
    try:
        started = time.perf_counter()
        vectors = await EmbeddingClient().embed(
            ["ทดสอบระบบค้นคืนเอกสารภาษาไทย", "second sentence for batch test"]
        )
        elapsed = time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001
        print(f"  [{FAIL}] {type(exc).__name__}: {exc}")
        return
    print(f"  [{OK}] {len(vectors)} เวกเตอร์ · {len(vectors[0])} มิติ · {elapsed:.2f} วินาที")
    if len(vectors[0]) != settings.embedding_dim:
        print(f"  [{FAIL}] มิติไม่ตรงกับตาราง chunks ({settings.embedding_dim})")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, help="ไฟล์ภาพสำหรับทดสอบ OCR")
    parser.add_argument("--pdf", type=Path, help="ไฟล์ PDF สำหรับทดสอบ OCR")
    parser.add_argument("--page", type=int, default=1, help="หน้าที่จะทดสอบ (ใช้กับ --pdf)")
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args()

    print(f"tier={settings.model_tier} · llm={settings.llm_model} · ocr={settings.typhoon_ocr_model}")

    models_ok = await step_models()
    await step_gpu()
    await step_embeddings()

    if not args.skip_ocr:
        image_path: Path | None = None
        if args.pdf:
            image_path = pdf_page_to_png(args.pdf, args.page)
        elif args.image:
            image_path = args.image

        if image_path is None:
            head("3. OCR — ข้าม")
            print("  ยังไม่ได้ระบุไฟล์ทดสอบ ใส่ --image หรือ --pdf เพื่อวัดเวลาต่อหน้าจริง")
        elif not image_path.exists():
            head("3. OCR — ข้าม")
            print(f"  [{FAIL}] ไม่พบไฟล์ {image_path}")
        elif models_ok:
            await step_ocr(image_path)

    if models_ok:
        await step_chat()

    head("สรุป")
    print("  เฟส 0 ผ่านเมื่อ: โมเดลครบ 2 ตัว · 100% GPU · OCR อ่านไทยออก · chat ตอบได้")
    print("  จดเวลาต่อหน้าไว้ — เฟส 3 ต้องใช้คำนวณ ETA ของคิว")


if __name__ == "__main__":
    asyncio.run(main())
