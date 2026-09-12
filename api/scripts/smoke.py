#!/usr/bin/env python
"""ทดสอบเส้นทางจริงผ่าน HTTP เหมือนที่หน้าเว็บเรียก

รัน:
    .\dc.ps1 exec api python scripts/smoke.py

ต่างจาก pytest: pytest ใช้ TestClient เรียก ASGI app ตรง ๆ ไม่ผ่าน uvicorn
จึงจับบั๊กที่เกิดจาก SSE buffering, ค่าใน .env ที่ container จริงเห็น,
หรือโมเดลที่ตอบไม่ตรงกฎ ไม่ได้เลย — สคริปต์นี้เรียกผ่าน HTTP จริงด้วยโมเดลจริง
"""
import json
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402

BASE = "http://localhost:8000"
CITE_MARK = re.compile(r"\[\d+\]")
# โมเดลอ้าง [2] ได้ถ้า chunk ที่ตรงอยู่อันดับสอง ซึ่งถูกต้อง ไม่ใช่แค่ [1]
THAI_CHARS = re.compile("[" + chr(0x0E00) + "-" + chr(0x0E7F) + "]")

def login(email, pw):
    r = httpx.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=60)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}

def sse(headers, payload, path="/api/chat"):
    out, cites, err, stages = "", [], None, []
    with httpx.stream("POST", BASE + path, headers=headers, json=payload, timeout=600) as r:
        if r.status_code != 200:
            r.read()
            return None, [], f"HTTP {r.status_code}: {r.text[:200]}", []
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                ev = next((l[7:] for l in block.split("\n") if l.startswith("event: ")), None)
                dt = next((l[6:] for l in block.split("\n") if l.startswith("data: ")), None)
                if not dt: continue
                d = json.loads(dt)
                if ev == "token": out += d["text"]
                elif ev == "citations": cites = d.get("citations", d if isinstance(d, list) else [])
                elif ev == "error": err = d
                elif ev == "meta": stages.append(d)
    return out, cites, err, stages

fails = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (f"  <- {detail}" if detail and not cond else ""))
    if not cond: fails.append(name)

print("=== 1. auth ===")
admin = login(settings.admin_email, settings.admin_password)
check("admin ล็อกอินได้", True)
bad = httpx.post(f"{BASE}/api/auth/login", json={"email": settings.admin_email, "password": "wrong"}, timeout=60)
check("รหัสผิดถูกปฏิเสธ 401", bad.status_code == 401, str(bad.status_code))
noauth = httpx.get(f"{BASE}/api/documents", timeout=30)
check("ไม่มี token เข้าไม่ได้", noauth.status_code == 401, str(noauth.status_code))

print("=== 2. แชทกับคำลงท้ายสุภาพ ===")
qs = [
    ("ค่าที่พักในกรุงเทพเบิกได้คืนละเท่าไหร่", "th", True),
    ("ลาป่วยต้องมีใบรับรองแพทย์เมื่อไหร่", "th", True),
    ("บริษัทมีรถรับส่งพนักงานไหม", "th", False),
    ("What is the per-diem for domestic travel?", "en", True),
]
p = settings.bot_polite_particle
for q, lang, expect_ctx in qs:
    t0 = time.perf_counter()
    ans, cites, err, _ = sse(admin, {"message": q})
    dt = time.perf_counter() - t0
    print(f"  ถาม [{lang}]: {q}")
    print(f"  ตอบ ({dt:.1f}s): {ans}")
    if err: check("ไม่มี error event", False, str(err)); continue
    if lang == "th":
        check("  ลงท้ายด้วย " + p, ans.rstrip(" .").endswith(p) or f"{p} [" in ans or f"{p}[" in ans, ans[-30:])
        check("  ใส่คำลงท้ายไม่เกิน 2 ครั้ง", ans.count(p) <= 2, f"นับได้ {ans.count(p)}")
    else:
        check("  คำตอบเป็นอังกฤษล้วน ไม่มีอักษรไทย", not THAI_CHARS.search(ans), ans[-60:])
    if expect_ctx:
        check("  อ้างอิงในข้อความ", bool(CITE_MARK.search(ans)), ans[-60:])
        check("  ส่ง citations event", len(cites) > 0, str(cites)[:100])
    else:
        check("  ปฏิเสธไม่เดา", "ไม่พบข้อมูล" in ans, ans[:60])

# session_id มาจาก SSE event "session" ไม่ใช่จาก endpoint list (ซึ่งไม่มี)
def sse_full(headers, payload):
    out, cites, err, sid = "", [], None, None
    with httpx.stream("POST", BASE + "/api/chat", headers=headers, json=payload, timeout=600) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                ev = next((l[7:] for l in block.split("\n") if l.startswith("event: ")), None)
                dt = next((l[6:] for l in block.split("\n") if l.startswith("data: ")), None)
                if not dt: continue
                d = json.loads(dt)
                if ev == "token": out += d["text"]
                elif ev == "citations": cites = d.get("citations", [])
                elif ev == "session": sid = d.get("session_id")
                elif ev == "error": err = d
    return out, cites, err, sid

a1, c1, e1, sid = sse_full(admin, {"message": "ลาพักร้อนได้ปีละกี่วัน"})
print(f"  ถาม: ลาพักร้อนได้ปีละกี่วัน\n  ตอบ: {a1}")
check("SSE ส่ง session_id กลับมา", bool(sid), str(sid))
if sid:
    a2, c2, e2, sid2 = sse_full(admin, {"message": "แล้วสะสมข้ามปีได้ไหม", "session_id": sid})
    print(f"  ถามต่อ (คำถามกำกวมถ้าไม่มีบริบท): แล้วสะสมข้ามปีได้ไหม\n  ตอบ: {a2}")
    check("session_id เดิมถูกใช้ต่อ ไม่สร้างใหม่", sid2 == sid, f"{sid} -> {sid2}")
    check("คำถามต่อเนื่องตอบได้", bool(a2) and not e2, str(e2))
    check("คำตอบต่อเนื่องเข้าใจว่าพูดถึงวันลา", any(k in a2 for k in ["ลา", "วัน", "สะสม", "ไม่พบข้อมูล"]), a2[:80])

print("=== 4. quota ของ user ธรรมดา ===")
uemail = f"qa-{uuid.uuid4().hex[:8]}@example.com"
cr = httpx.post(f"{BASE}/api/admin/users", headers=admin,
                json={"email": uemail, "password": "TestPass123!", "role": "user"}, timeout=60)
check("สร้าง user ได้", cr.status_code in (200, 201), f"{cr.status_code} {cr.text[:150]}")
uid = cr.json().get("id") if cr.status_code in (200, 201) else None
if uid:
    uh = login(uemail, "TestPass123!")
    st = httpx.get(f"{BASE}/api/me/quota", headers=uh, timeout=60)
    check("user ดูโควตาตัวเองได้", st.status_code == 200, f"{st.status_code} {st.text[:150]}")
    if st.status_code == 200:
        q = st.json()
        print(f"  โควตาเริ่มต้น: {json.dumps(q, ensure_ascii=False)}")
        check("โควตาเริ่มที่ 0 ไม่ใช่ null", q["documents"]["used"] == 0 and q["pages"]["used"] == 0, str(q))
    forb = httpx.get(f"{BASE}/api/admin/users", headers=uh, timeout=60)
    check("user เข้าหน้า admin ไม่ได้ 403", forb.status_code == 403, str(forb.status_code))
    dl = httpx.delete(f"{BASE}/api/admin/users/{uid}", headers=admin, timeout=60)
    check("ลบ user ทดสอบได้", dl.status_code in (200, 204), str(dl.status_code))

print("=== 5. playground ===")
dp = httpx.get(f"{BASE}/api/admin/prompt-configs/default", headers=admin, timeout=60)
check("ดึง default prompt ได้", dp.status_code == 200, str(dp.status_code))
if dp.status_code == 200:
    sp = dp.json()["system_prompt"]
    check("prompt มีคำลงท้ายที่ตั้งไว้", p in sp, sp[-120:])
pr = httpx.post(f"{BASE}/api/admin/playground/query", headers=admin,
                json={"message": "ลาพักร้อนได้ปีละกี่วัน"}, timeout=600)
check("playground run สำเร็จ", pr.status_code == 200, f"{pr.status_code} {pr.text[:200]}")
if pr.status_code == 200:
    b = pr.json()
    print(f"  playground ตอบ: {b.get('answer','')[:120]}")
    check("playground คืน hits", len(b.get("hits") or b.get("citations") or []) > 0, str(list(b.keys())))

print("=== 6. analytics ===")
for path in ["/api/admin/analytics/overview", "/api/admin/analytics/ingestion"]:
    r = httpx.get(BASE + path, headers=admin, timeout=60)
    check(f"{path} 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

print("=== 6.5 ประวัติบทสนทนา ===")
r = httpx.get(f"{BASE}/api/chat/sessions", headers=admin, timeout=60)
check("ดึงรายการบทสนทนาได้", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
if r.status_code == 200:
    rows = r.json()
    check("บทสนทนาที่เพิ่งคุยอยู่ในรายการ", any(x["id"] == sid for x in rows), sid)
    row = next((x for x in rows if x["id"] == sid), None)
    if row:
        print("  " + json.dumps(row, ensure_ascii=False))
        check("หัวข้อไม่ว่าง", bool(row["title"].strip()), row["title"])
        check("นับข้อความได้อย่างน้อย 4", row["message_count"] >= 4, row["message_count"])
    d = httpx.get(f"{BASE}/api/chat/sessions/{sid}", headers=admin, timeout=60)
    check("เปิดบทสนทนาเดิมได้", d.status_code == 200, str(d.status_code))
    if d.status_code == 200:
        ms = d.json()["messages"]
        check("อ่านข้อความกลับมาครบ", len(ms) >= 4, len(ms))
        answers = [m for m in ms if m["role"] == "assistant"]
        check("คำตอบมีที่มาแนบมาด้วย", bool(answers) and len(answers[0]["citations"]) > 0,
              str(answers[:1])[:150])
        check("ที่มามีชื่อเอกสาร", bool(answers[0]["citations"][0]["document_name"]),
              str(answers[0]["citations"][0]))

print("=== 7. rate limit ===")
codes = []
for _ in range(settings.rate_limit_chat_per_minute + 3):
    r = httpx.post(f"{BASE}/api/chat", headers=admin, json={"message": "hi"}, timeout=600)
    codes.append(r.status_code)
    r.close()
    if r.status_code == 429: break
check("แชทถี่เกินโดน 429", 429 in codes, f"ได้ {codes[-3:]}")

print()
print("=" * 50)
print(f"ล้มเหลว {len(fails)} รายการ" if fails else "ผ่านทั้งหมด")
for f in fails: print("  - " + f)
sys.exit(1 if fails else 0)
