# RAG Workshop

ระบบ RAG chatbot ภาษาไทย — ingestion + OCR, retrieval, chat widget, playground, analytics
รันทุกอย่างผ่าน Docker ไม่ต้องติดตั้ง Python หรือ Ollama บน Windows

แผนงานฉบับเต็มอยู่ใน **[PLAN.md](PLAN.md)** — สถาปัตยกรรม การตัดสินใจ ข้อจำกัดฮาร์ดแวร์ และเฟสงาน

---

## Stack

| ชั้น | ใช้อะไร |
|---|---|
| Chat LLM | `Qwen3.5-4B` Q4_K_M บน Ollama |
| OCR | `typhoon-ocr1.5-2b` Q4_K_M บน Ollama |
| Embedding | `BAAI/bge-m3` บน HF Text-Embeddings-Inference (CPU) |
| Backend | FastAPI + Celery |
| Database | PostgreSQL 16 + pgvector |
| Frontend | Next.js 15 |
| Proxy | Caddy |

โมเดลทุกตัวคุยผ่าน OpenAI-compatible API → ย้ายไปการ์ดใหญ่ (vLLM + Qwen3.8-27B) ทำได้โดยแก้ `.env` ไม่ต้องแตะโค้ด

---

## เริ่มใช้งานครั้งแรก

### 1. ปรับ RAM ของ WSL2
WSL2 ตั้ง default ที่ 50% ของเครื่อง (8.26 GB จาก 16 GB) ซึ่งไม่พอสำหรับ stack นี้ (~6–6.5 GB)

```powershell
Copy-Item wslconfig.example $env:USERPROFILE\.wslconfig
wsl --shutdown
```
เปิด Docker Desktop ใหม่หลังจากนั้น

### 2. สร้าง `.env`
```powershell
Copy-Item .env.example .env
```
เติม `POSTGRES_PASSWORD`, `APP_SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`

### 3. ขึ้น stack
```powershell
.\dc.ps1 up -d --build
```
ครั้งแรกใช้เวลานาน — TEI ต้องโหลด bge-m3 (~2.3 GB) และ build image ของ api/web

### 4. โหลดโมเดลเข้า Ollama
```powershell
# ทีละตัว — โหลดพร้อมกันช้ากว่ามาก
.\dc.ps1 exec ollama ollama pull scb10x/typhoon-ocr1.5-3b
.\dc.ps1 exec ollama ollama cp scb10x/typhoon-ocr1.5-3b typhoon-ocr
.\dc.ps1 exec ollama ollama pull qwen3.5:4b
```

ขนาดที่ต้องโหลด: typhoon-ocr Q4_K_M 1.11GB + mmproj 445MB · qwen3.5:4b 3.4GB
บนเน็ตที่วัดได้ ~227 KB/s รวมแล้วราว 6 ชั่วโมง — โหลดทีละตัว อย่าพร้อมกัน

`ollama cp` ตั้งชื่อสั้นให้ตรงกับ `TYPHOON_OCR_MODEL=typhoon-ocr` ใน `.env`
ถ้าเปลี่ยน quantization ก็แค่ pull ตัวใหม่แล้ว `cp` ทับชื่อเดิม โค้ดไม่ต้องแก้

### 5. รัน migration
```powershell
.\dc.ps1 exec api alembic upgrade head
```

### 6. ตรวจว่าทุกอย่างพร้อม (เฟส 0)
```powershell
.\dc.ps1 exec api python scripts/spike.py --pdf /data/uploads/test.pdf
```

สคริปต์นี้จะบอก:
- โมเดลครบทั้งสองตัวไหม
- **โมเดลรันบน GPU 100% หรือหล่นไป CPU** ← ข้อสำคัญที่สุด
- OCR อ่านหน้าเอกสารไทยออกเป็น markdown ไหม
- **เวลาต่อหน้าจริง** — เอาไปคำนวณ ETA ของคิวในเฟส 3

หรือดูผ่านหน้าเว็บที่ http://localhost:3000 และ API ที่ http://localhost:8000/health/deep

---

## คำสั่งประจำวัน

```powershell
.\dc.ps1 up -d                              # ขึ้นทั้ง stack
.\dc.ps1 down                               # ปิด (ข้อมูลอยู่ใน volume ไม่หาย)
.\dc.ps1 logs -f worker                     # ดู log งาน OCR
.\dc.ps1 exec api alembic upgrade head      # migration
.\dc.ps1 exec api alembic revision -m "..."  # สร้าง migration ใหม่
.\dc.ps1 exec api pytest                    # เทส
.\dc.ps1 exec ollama ollama ps              # PROCESSOR ต้องเป็น 100% GPU
docker stats                                # ดู RAM ต่อคอนเทนเนอร์
```

`dc.ps1` แค่ห่อ `docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.override.yml`
ตั้ง `$env:RAG_ENV = 'prod'` เพื่อข้าม override (hot reload) และ `$env:RAG_TIER = 'prod'` เพื่อใช้ vLLM แทน Ollama

---

## ข้อจำกัดที่ต้องรู้

เครื่องนี้เป็น **RTX 3050 6GB** วัดจากในคอนเทนเนอร์แล้วเหลือ VRAM ว่างจริง **~4.3 GB** และไม่มีการ์ดออนบอร์ดให้สลับไปขับจอ

- **โหลดได้ทีละโมเดล** `OLLAMA_MAX_LOADED_MODELS=1` เป็นข้อบังคับ สลับ OCR ↔ chat เสีย cold start 5–15 วินาที
- **OCR ~20–30 วินาที/หน้า** → 500 หน้า = 3–4 ชั่วโมง ต้องเป็น background queue เสมอ
- **รองรับราว 1–2 users** ที่ใช้โควตาเต็ม (5 เอกสาร / 500 หน้าต่อวัน)
- **ถ้า VRAM ไม่พอ Ollama จะไม่ error** แต่ย้าย layer ไป CPU แล้วช้าลง 5–10 เท่าเงียบ ๆ — เช็คด้วย `ollama ps` หรือ `/health/deep`

เกณฑ์ว่าเมื่อไหร่ควรขยับไปการ์ดใหญ่อยู่ใน [PLAN.md](PLAN.md) ข้อ 14.2

---

## โครงสร้าง

```
├── PLAN.md                    แผนงานฉบับเต็ม
├── docker-compose.yml         app stack
├── docker-compose.local.yml   Ollama + GPU (tier LOCAL)
├── docker-compose.gpu.yml     vLLM (tier PROD — ยังไม่ได้เขียน)
├── dc.ps1                     ตัวช่วยเรียก docker compose
├── caddy/Caddyfile
├── api/
│   ├── alembic/               migration
│   ├── scripts/spike.py       สคริปต์ตรวจเฟส 0
│   └── app/
│       ├── core/              config, db, security
│       ├── models/            SQLAlchemy
│       ├── routers/           FastAPI endpoints
│       ├── llm/               ChatClient, ollama_admin
│       ├── retrieval/         EmbeddingClient
│       └── ingestion/         TyphoonOcrClient
└── web/                       Next.js
```
