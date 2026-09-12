#!/usr/bin/env python
"""วัดคุณภาพ retrieval ด้วยชุดคำถามที่รู้คำตอบ

รัน:
    .\\dc.ps1 exec api python scripts/eval.py
    .\\dc.ps1 exec api python scripts/eval.py --set /app/evalsets/hr.json --top-k 5

ทำไมต้องมี: การปรับ min_score, chunk size, หรือเปิด/ปิด hybrid ล้วนเป็นการแลกได้แลกเสีย
ถ้าไม่มีตัวเลขก็ตัดสินไม่ได้ว่าเปลี่ยนแล้วดีขึ้นจริงหรือแค่รู้สึกว่าดีขึ้น

รูปแบบไฟล์ชุดคำถาม (JSON list):
    {"question": "...", "expect": "ข้อความที่ต้องปรากฏใน chunk ที่ค้นเจอ"}
    {"question": "...", "expect_none": true}   # คำถามที่ระบบ *ต้องไม่* ตอบ

ตัววัด:
    hit@1 / hit@k  สัดส่วนคำถามที่เจอคำตอบในอันดับ 1 / k อันดับแรก
    MRR            ค่าเฉลี่ยของ 1/อันดับที่เจอ — ลงโทษการเจอในอันดับท้าย ๆ
    ปฏิเสธถูก      สัดส่วนคำถามที่ไม่มีคำตอบแล้วระบบไม่ตอบ (กัน false positive)
"""
import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db import SessionLocal  # noqa: E402
from app.retrieval.embeddings import EmbeddingClient  # noqa: E402
from app.retrieval.search import search  # noqa: E402


@dataclass
class Result:
    mode: str
    total: int
    answerable: int
    hit1: int
    hitk: int
    mrr_sum: float
    unanswerable: int
    correct_rejections: int

    def report(self, top_k: int) -> str:
        def pct(n: int, d: int) -> str:
            return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "—"

        mrr = self.mrr_sum / self.answerable if self.answerable else 0.0
        return (
            f"  hit@1      {pct(self.hit1, self.answerable)}\n"
            f"  hit@{top_k}      {pct(self.hitk, self.answerable)}\n"
            f"  MRR        {mrr:.3f}\n"
            f"  ปฏิเสธถูก   {pct(self.correct_rejections, self.unanswerable)}"
        )


async def evaluate(
    cases: list[dict], *, hybrid: bool, top_k: int, min_score: float | None
) -> tuple[Result, list[str]]:
    embedder = EmbeddingClient()
    result = Result("hybrid" if hybrid else "vector", len(cases), 0, 0, 0, 0.0, 0, 0)
    failures: list[str] = []

    async with SessionLocal() as session:
        for case in cases:
            question = case["question"]
            vector = await embedder.embed_one(question)
            hits = await search(
                session,
                vector,
                question=question,
                top_k=top_k,
                min_score=min_score,
                hybrid=hybrid,
            )

            if case.get("expect_none"):
                result.unanswerable += 1
                if not hits:
                    result.correct_rejections += 1
                else:
                    failures.append(
                        f"  ตอบทั้งที่ไม่ควรตอบ: {question}\n"
                        f"     คะแนนสูงสุด {hits[0].score:.3f} — {hits[0].text[:60]}…"
                    )
                continue

            result.answerable += 1
            expect = case["expect"]
            found = next((i for i, h in enumerate(hits, 1) if expect in h.text), None)
            if found is None:
                top = f"{hits[0].score:.3f}" if hits else "ไม่มีผลลัพธ์"
                failures.append(f"  หาไม่เจอ: {question}\n     คาดว่าต้องมี '{expect}' · สูงสุด {top}")
                continue
            result.mrr_sum += 1 / found
            result.hitk += 1
            if found == 1:
                result.hit1 += 1

    return result, failures


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", dest="path", default="/app/evalsets/hr.json")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--show-failures", action="store_true", default=True)
    parser.add_argument("--quiet", dest="show_failures", action="store_false")
    args = parser.parse_args()

    cases = json.loads(Path(args.path).read_text(encoding="utf-8"))
    answerable = sum(1 for c in cases if not c.get("expect_none"))
    print(f"ชุดคำถาม: {args.path}")
    print(f"  {len(cases)} ข้อ (มีคำตอบ {answerable} · ไม่มีคำตอบ {len(cases) - answerable})")
    print(f"  top_k={args.top_k} min_score={args.min_score if args.min_score is not None else 'ค่าจาก .env'}\n")

    for hybrid in (False, True):
        result, failures = await evaluate(
            cases, hybrid=hybrid, top_k=args.top_k, min_score=args.min_score
        )
        print(f"[{result.mode}]")
        print(result.report(args.top_k))
        if failures and args.show_failures:
            print("  --- ข้อที่พลาด ---")
            for line in failures:
                print(line)
        print()


asyncio.run(main())
