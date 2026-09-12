# RAG Workshop — แผนการสร้างระบบ (self-hosted)

เอกสารนี้แปลงไดอะแกรมสถาปัตยกรรม 2 รูป (runtime + ingestion pipeline) ให้เป็นแผนสร้างจริงบน Docker
**ทุกโมเดลรันเอง ไม่พึ่ง API ภายนอก** — `.env` ยังมีช่องใส่ API key ครบ เผื่อสลับไป hosted endpoint

---

## 1. ข้อสรุปจากไดอะแกรม

### 1.1 Runtime flow
```
ผู้ใช้ (Chat widget)
        │
        ▼
   Backend core  ──► Vector database
 (retrieval +    ──► LLM server   (OpenAI-compatible)
  orchestration) ──► OCR server   (OpenAI-compatible)
        ▲
        └────────────── Ingestion + OCR / Playground (dashboard)

Dashboard = Ingestion+OCR | Playground | Analytics/logs
```

### 1.2 Ingestion pipeline
```
อัปโหลดเอกสาร → เช็คโควตา → ตรวจสอบประเภทไฟล์ (รายหน้า)
        ├─ ภาพ/สแกน ──► OCR extraction (typhoon-ocr)
        └─ ข้อความอยู่แล้ว ──► Direct text parse (docx, txt, html, PDF-text)
                    │
                    ▼
          แบ่ง chunk + ทำความสะอาดข้อความ
                    ▼
              สร้าง embedding ──► Vector database
```

---

## 2. ฮาร์ดแวร์ที่มี vs. ที่โมเดลต้องการ

ตรวจแล้วเครื่องปัจจุบัน: **NVIDIA GeForce RTX 3050, VRAM 6144 MiB, driver 560.94, compute capability 8.6**

**วัดจากในคอนเทนเนอร์จริง** (`docker run --gpus all … nvidia-smi`) ขณะเปิด VSCode + browser ตามปกติ:
```
NVIDIA GeForce RTX 3050, 6144 MiB total, 4300 MiB free
```
→ **เหลือใช้จริง ~4.3 GB** ไม่ใช่ 5 GB และเครื่องนี้**ไม่มีการ์ดออนบอร์ด** — RTX 3050 เป็นตัวเดียวและต้องขับจอ 1920px ด้วย ~1.8 GB ก้อนนี้จึงเอาคืนไม่ได้ (ถ้ามี iGPU จะสลับให้ iGPU ขับจอแล้วปล่อย 3050 ว่างทั้งใบได้ แต่เคสนี้ทำไม่ได้)

⚠️ ตัวเลข 4.3 GB **ไม่คงที่** — เปิด browser หลายแท็บอาจเหลือ ~3.5 GB งบโมเดลจึงต้องเผื่อไว้ที่ **~3.5 GB ไม่ใช่ 4.3 GB**

| โมเดลที่ตั้งใจไว้ | ต้องการ | สถานะบน 3050 6GB |
|---|---|---|
| `Qwen/Qwen3.8-27B-FP8` | ~28 GB weights + KV → กัน ~40 GB | ❌ ต่างกัน ~8 เท่า ไม่มีทางบีบลง |
| `typhoon-ai/typhoon-ocr-7b` (BF16) | ~16 GB + KV → กัน ~22 GB | ❌ ไม่พอ |
| `typhoon-ai/typhoon-ocr-7b` Q4_K_M | ~4.5 GB + vision + KV ≈ 5.5 GB | ⚠️ ชนเพดานพอดี ไม่เหลือให้โมเดลอื่น |
| `typhoon-ocr1.5-2b` GGUF จาก HF | ~2.3 GB | ❌ **ไม่ใช้** — ดูเหตุผลด้านล่าง |
| **`scb10x/typhoon-ocr1.5-3b`** (Q4_K_M QAT) | **~3.2 GB** | ✅ **เลือกตัวนี้** |
| **`qwen3.5:4b`** Q4_K_M | **~3.4 GB** | ✅ ลงได้ (ทีละตัว) |
| `qwen3.5:2b` | ~2.7 GB | 🅱️ fallback ถ้า 4B ตกไป CPU บ่อย |
| `BAAI/bge-m3` | ~1.2 GB (หรือรันบน CPU) | ✅ ให้รัน CPU ไปเลย |

**ตัดสินใจเรื่อง quantization:** ใช้ **Q4_K_M ทั้งคู่** ไม่ใช่ Q8 — งบจริงคือ ~3.5 GB (เผื่อ VRAM ที่แกว่ง) ตัว OCR เป็น Q4_K_M แบบ **QAT** คือเทรนมาให้ทน quantization ตั้งแต่แรก ไม่ใช่บีบทีหลัง คุณภาพจึงใกล้ half-precision

**ทำไมเปลี่ยนจาก 2b (HF) เป็น 3b (Ollama registry) ทั้งที่ใหญ่กว่า:**
วัดความเร็วดาวน์โหลดจากเครื่องนี้แล้วต่างกันมหาศาล

| ปลายทาง | ความเร็ว | เวลาที่ต้องใช้ |
|---|---|---|
| huggingface.co | 7–36 KB/s | ~12 ชั่วโมง (1.55 GB) |
| github.com | 178 KB/s | — |
| **registry.ollama.ai** | **315–500 KB/s** | **~2–3 ชั่วโมง (3.2 GB)** |

ใหญ่กว่าเท่าตัวแต่เร็วกว่า 6 เท่า และได้ของดีกว่าด้วย: publish โดย SCB10X เอง (ไม่ใช่ GGUF ที่คนอื่น re-upload),
Ollama จัดการ mmproj ให้เอง ความเสี่ยงเรื่อง vision ที่เป็น blocker ของเฟส 0 จึงหายไปทั้งหมด

**ข้อเท็จจริงสำคัญ:** ตระกูล **Qwen3.8 ไม่มีรุ่นเล็ก** — เจนนี้มีแค่ 27B (dense), Flash-Next 180B-A6B และ Max ถ้าต้องการ 4B/9B ต้องถอยไปตระกูล **Qwen3.5** (0.8B / 2B / 4B / 9B / 27B) หรือ **Qwen3** (0.6B / 1.7B / 4B / 8B / 14B / 32B)

---

## 3. Model tier — **ตัดสินใจแล้ว: ใช้ Tier LOCAL เป็น production**

โค้ดชุดเดียวกันรองรับทั้งสามแบบ เพราะทุก runtime พูด OpenAI-compatible API เหมือนกัน **เปลี่ยนแค่ `.env`**
Tier MID/PROD ยังเขียนไว้เป็นเส้นทางขยาย ไม่ต้องแก้โค้ดตอนย้าย

### ✅ Tier LOCAL — รันบน RTX 3050 6GB ได้ทั้งหมด *(ตัวที่ใช้จริง)*
| บทบาท | โมเดล | Runtime | VRAM |
|---|---|---|---|
| OCR | `scb10x/typhoon-ocr1.5-3b` Q4_K_M (QAT) | Ollama | ~3.2 GB |
| Chat | `qwen3.5:4b` Q4_K_M | Ollama | ~3.4 GB |
| Embedding | `bge-m3` | TEI **บน CPU** | 0 (ใช้ RAM ~1.5 GB) |

> โหลดพร้อมกันสองตัว = ~5–6 GB ซึ่งเกินพอดี → ให้ **Ollama สลับโหลดอัตโนมัติ** (`OLLAMA_MAX_LOADED_MODELS=1`, จูน `keep_alive`) เสีย cold start ~5–15 วินาทีตอนสลับ ซึ่งรับได้เพราะ ingestion กับ chat แทบไม่เกิดพร้อมกัน

### Tier PROD — ตามที่ requirement ตั้งไว้เดิม *(เส้นทางขยาย)*
| บทบาท | โมเดล | Runtime | VRAM |
|---|---|---|---|
| OCR | `typhoon-ocr-7b` หรือ `typhoon-ocr1.5-2b` BF16 | vLLM | ~22 GB / ~8 GB |
| Chat | `Qwen3.8-27B-FP8` | vLLM | ~40 GB |
| Embedding | `bge-m3` | TEI (GPU) | ~2 GB |

การ์ดที่ลงตัว: **1× L40S / A6000 48GB** (พอสำหรับทั้งคู่ถ้าใช้ OCR 2B) หรือ 1× A100/H100 80GB

### Tier MID — ทางสายกลาง ถ้าจะซื้อการ์ดใบเดียวจบ *(เส้นทางขยาย)*
| บทบาท | โมเดล | VRAM |
|---|---|---|
| OCR | `typhoon-ocr1.5-2b` BF16 | ~8 GB |
| Chat | `Qwen3.5-9B` หรือ `Qwen3-14B` AWQ | ~10–12 GB |

ลงได้บน **RTX 4090 / 5090 (24–32GB)** ใบเดียว คุณภาพห่างจาก 27B ไม่มากในงาน RAG

---

## 4. กำลังเครื่องจริง (วัดแล้ว 8 ก.ย. 2026)

> **ตัวเลขที่วัดได้จริงดีกว่าที่ประเมินไว้เดิม 5 เท่า** — ส่วนที่ 4 เดิม (ด้านล่าง) ประเมินไว้
> 25 วินาที/หน้า ซึ่งมองโลกในแง่ร้ายเกินไปมาก เก็บไว้เป็นบันทึกว่าเคยคิดผิดอย่างไร

วัดด้วย `typhoon-ocr1.5-2b` Q4_K_M บน RTX 3050 6GB กับหน้าเอกสารไทย A4 ที่ 150 dpi:

| รายการ | ผล |
|---|---|
| รอบแรก (รวมโหลดโมเดลเข้า VRAM) | 17.5 วินาที |
| **รอบต่อไป (โมเดลอยู่ใน VRAM)** | **5.2 วินาที/หน้า · 72.7 tok/s** |
| สถานะ GPU | `100% GPU` ไม่หล่นไป CPU |
| คุณภาพ | อ่านไทยถูกทุกตัว **และแปลงตารางเป็น HTML `<table>` ให้เอง** |

| โหลด | เวลาที่ใช้จริง |
|---|---|
| 20 หน้า | ~2 นาที |
| 500 หน้า (โควตาเต็มของ user 1 คน) | **~43 นาที** |
| 500 หน้า × 5 users | ~3.6 ชั่วโมง ✅ ทันในหนึ่งวัน |

**สรุปใหม่:** เครื่องนี้รองรับได้ราว **5–10 users** ที่ใช้โควตาเต็ม ไม่ใช่ 1–2 คนอย่างที่ประเมินไว้เดิม

⚠️ หน้าที่ใช้วัดเป็นภาพเรนเดอร์สะอาด สแกนจริงที่มี noise เอียง หรือลายมือจะช้ากว่านี้
จึงตั้ง `OCR_SECONDS_PER_PAGE=10` เผื่อไว้ — ค่าจริงจากงานที่รันไปแล้วดูได้ที่
`/api/admin/analytics/ingestion` (`seconds_per_page`) แล้วเอามาแก้ `.env` ให้ ETA แม่นขึ้น

---

## 4ก. (บันทึกเดิม) ประมาณการก่อนวัดจริง: 500 หน้า/วัน บน 3050 ใช้เวลาเท่าไหร่

RTX 3050 6GB มี memory bandwidth ~170 GB/s → typhoon-ocr1.5-2b Q4 ทำได้ราว 40–60 tok/s
หน้าเอกสารไทยหนาแน่นให้ output markdown ราว 800–1,200 token → **~20–30 วินาที/หน้า**

| โหลด | เวลาที่ใช้บน 3050 |
|---|---|
| 20 หน้า (ทดสอบ) | ~8–10 นาที |
| 500 หน้า (โควตา 1 user/วัน) | **~3–4 ชั่วโมง** |
| 500 หน้า × 5 users | ~17 ชั่วโมง ❌ ไม่ทันในหนึ่งวัน |

**สรุป:** 3050 รองรับได้ประมาณ **1–2 users ที่ใช้โควตาเต็ม** และ ingestion ต้องเป็น background queue เท่านั้น ห้ามให้ user รอหน้าจอ
ถ้ามี user เกิน 2 คนที่ใช้เต็มโควตา ต้องขยับไป Tier MID/PROD

---

## 5. Tech stack

| ชั้น | เลือกใช้ | เหตุผล |
|---|---|---|
| Backend core | **FastAPI (Python 3.11)** | `typhoon-ocr` เป็น Python package |
| Async worker | **Celery + Redis** | OCR 500 หน้า = หลายชั่วโมง ต้องไม่ block HTTP |
| DB + Vector DB | **PostgreSQL 16 + pgvector** | รวม metadata, chunk, chat log, quota, feedback ที่เดียว |
| Model serving (LOCAL) | **Ollama (ในคอนเทนเนอร์)** | GGUF, auto load/unload (สำคัญมากกับ 6GB), OpenAI-compatible, GPU ผ่าน WSL2 passthrough |
| Model serving (PROD) | **vLLM** | throughput สูง, FP8, continuous batching |
| Embedding serving | **HF Text-Embeddings-Inference** | มี CPU image, เบากว่าเอา vLLM มาทำ |
| Frontend | **Next.js 15 + TS + Tailwind + shadcn/ui** | dashboard + chat widget ในโปรเจกต์เดียว |
| Chat widget | bundle แยก (Vite → IIFE `widget.js`) | ฝังเว็บลูกค้าด้วย `<script>` แท็กเดียว |
| Reverse proxy | **Caddy** | auto-TLS, config สั้น |

**ทำไมไม่ใช้ vLLM บนเครื่องนี้:** vLLM จองหน่วยความจำล่วงหน้าเป็นก้อนใหญ่ ไม่รองรับ GGUF ดีนัก และไม่มี auto-unload — บน 6GB จะ OOM ทันทีที่ต้องใช้สองโมเดล ส่วน Ollama ออกแบบมาเพื่อกรณีนี้พอดี

---

## 6. คอนเทนเนอร์ — **รันทุกอย่างผ่าน Docker**

ไม่ต้องลงอะไรบน Windows นอกจาก Docker Desktop เลย ทั้ง Python, Ollama, poppler อยู่ในคอนเทนเนอร์หมด

```
docker-compose.yml  (ทุก tier)                    docker-compose.gpu.yml (เส้นทางขยาย)
├── caddy      :80/:443                           ├── llm  :8001  vLLM
├── web        :3000  Next.js                     ├── ocr  :8002  vLLM
├── api        :8000  FastAPI                     └── embeddings :8080 TEI-GPU
├── worker     —      Celery
├── postgres   :5432  pgvector/pgvector:pg16
├── redis      :6379
├── embeddings :8080  TEI **CPU image**
└── ollama     :11434 **GPU** (docker-compose.local.yml)
```

`api` กับ `worker` ใช้ image เดียวกัน ต่างแค่ command

### 6.1 Ollama ในคอนเทนเนอร์ + GPU passthrough

```yaml
  ollama:
    image: ollama/ollama:latest
    environment:
      OLLAMA_MAX_LOADED_MODELS: "1"     # ห้ามเกิน 1 บน 6GB
      OLLAMA_KEEP_ALIVE: "5m"
      OLLAMA_NUM_PARALLEL: "1"
    volumes: ["ollama-models:/root/.ollama"]   # ~5GB, อย่าใช้ bind mount ไป NTFS จะช้ามาก
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

โหลดโมเดลครั้งแรก (ไม่ต้องมี Ollama บน Windows):
```powershell
# ทีละตัว — โหลดพร้อมกันทำให้ช้าลงหลายเท่า
docker compose exec ollama ollama pull scb10x/typhoon-ocr1.5-3b
docker compose exec ollama ollama cp scb10x/typhoon-ocr1.5-3b typhoon-ocr
docker compose exec ollama ollama pull qwen3.5:4b
```

**เงื่อนไขที่ต้องผ่าน:** Docker Desktop ใช้ WSL2 backend (ไม่ใช่ Hyper-V) + NVIDIA driver บน Windows
ตรวจแล้วเครื่องนี้: WSL2 default version 2 ✅ · distro `docker-desktop` running ✅ · driver 560.94 ✅ · Docker 29.4.3 ✅
**ไม่ต้องลง NVIDIA Container Toolkit เอง** — Docker Desktop จัดการให้แล้ว

คำสั่งพิสูจน์:
```powershell
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

### 6.2 ⚠️ ราคาที่ต้องจ่ายกับการใส่ทุกอย่างลง Docker

**VRAM** — วัดจริงในคอนเทนเนอร์แล้วเหลือ **4300 MiB** (ดูข้อ 2) ซึ่งรวม overhead ของ WSL2 passthrough ไว้แล้ว
พอสำหรับโมเดลทีละตัวที่ Q4_K_M (2.3–2.9 GB) แต่ยืนยันได้เลยว่า **โหลดสองโมเดลพร้อมกันไม่ได้แน่นอน** `OLLAMA_MAX_LOADED_MODELS=1` จึงไม่ใช่ทางเลือกแต่เป็นข้อบังคับ

**กับดักเงียบที่ต้องเฝ้า:** ถ้า VRAM ไม่พอ Ollama จะ**ไม่ error** แต่จะย้ายบาง layer ไปรันบน CPU ซึ่งช้าลง 5–10 เท่าโดยไม่บอกอะไรเลย ตรวจด้วย:
```powershell
docker compose exec ollama ollama ps
```
ดูคอลัมน์ `PROCESSOR` — ต้องเป็น `100% GPU` ถ้าขึ้นเป็น `x% CPU / y% GPU` แปลว่าล้นแล้ว ให้ปิด browser หรือลด quantization ลง
ควรใส่ health check นี้ในเฟส 0 และ log ค่านี้ทุกครั้งที่ job เริ่ม เพราะเป็นสาเหตุอันดับหนึ่งที่ OCR จะช้าผิดปกติ

**RAM** — WSL2 ตั้งค่า default ที่ 50% ของ RAM เครื่อง ตอนนี้ VM ได้ **8.26 GB** จาก 16 GB
ประมาณการที่ต้องใช้: TEI bge-m3 บน CPU ~2.5–3 GB · postgres ~0.5 · redis ~0.25 · api+worker ~1 · web (Next dev) ~1 · ollama ~0.5 = **~6–6.5 GB** เหลือ headroom น้อยเกินไป

สร้าง `C:\Users\PC\.wslconfig` แล้ว restart WSL:
```ini
[wsl2]
memory=10GB
processors=8
swap=4GB
```
เหลือให้ Windows ~6 GB (พอสำหรับ VSCode + browser)

**ถ้า RAM ยังตึง** ทางลดที่ไม่กระทบคุณภาพ: ใช้ TEI แบบ ONNX int8 สำหรับ bge-m3 ลดจาก ~2.5 GB เหลือ ~0.8 GB · หรือรัน `web` (Next.js) บน Windows ด้วย Node ที่มีอยู่แล้ว แทนที่จะใส่คอนเทนเนอร์ตอน dev

**ดิสก์** — ว่าง 97.5 GB เพียงพอ (model ~5 GB + images ~8 GB + WSL VM disk ที่โตขึ้นเรื่อย ๆ)

### 6.2 คำสั่ง vLLM (Tier PROD)
```yaml
  llm:
    image: vllm/vllm-openai:v0.11.0     # pin เวอร์ชันที่รองรับ Gated DeltaNet ตาม recipe ใน model card
    command: >
      --model Qwen/Qwen3.8-27B-FP8
      --served-model-name qwen3.8-27b
      --max-model-len 32768
      --gpu-memory-utilization 0.90
      --kv-cache-dtype fp8
  ocr:
    command: >
      --model typhoon-ai/typhoon-ocr1.5-2b
      --served-model-name typhoon-ocr
      --max-model-len 49152
```
**context 32768 ไม่ใช่ 262144** — RAG ใช้ไม่ถึง แต่ KV cache ที่ 262k กินเป็นสิบ GB ฟรี ๆ

### 6.3 image ฝั่ง api/worker
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils libmagic1 && rm -rf /var/lib/apt/lists/*
```
`poppler-utils` ใช้ `pdftoppm` แปลงหน้าเป็นภาพ (และ `pdftotext` สำหรับ anchor text ถ้าใช้ typhoon-ocr รุ่น 7b)

---

## 7. `.env`

```dotenv
# ---------- Model tier: local | mid | prod ----------
MODEL_TIER=local

# ---------- LLM ----------
# local : http://ollama:11434/v1   (Ollama ในคอนเทนเนอร์)
# prod  : http://llm:8000/v1       (vLLM)
LLM_BASE_URL=http://ollama:11434/v1
LLM_API_KEY=                       # Ollama/vLLM ไม่ต้องใช้; เว้นไว้เผื่อสลับไป hosted
LLM_MODEL=qwen3.5:4b               # prod: qwen3.8-27b
LLM_HF_REPO=Qwen/Qwen3.5-4B        # prod: Qwen/Qwen3.8-27B-FP8
LLM_MAX_MODEL_LEN=8192             # prod: 32768
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=1024
LLM_TIMEOUT_SECONDS=180
LLM_ENABLE_THINKING=false

# ---------- OCR ----------
TYPHOON_OCR_BASE_URL=http://ollama:11434/v1
TYPHOON_OCR_API_KEY=               # ใส่เมื่อใช้ api.opentyphoon.ai
TYPHOON_OCR_MODEL=typhoon-ocr
TYPHOON_OCR_HF_REPO=typhoon-ai/typhoon-ocr1.5-2b
TYPHOON_OCR_TASK_TYPE=default      # default | structure
TYPHOON_OCR_CONCURRENCY=1          # 3050 ทำได้ทีละหน้า อย่าตั้งเกิน 1
TYPHOON_OCR_PAGE_TIMEOUT=120

# ---------- Embedding ----------
EMBEDDING_BASE_URL=http://embeddings:8080
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024
EMBEDDING_DEVICE=cpu               # local: cpu | prod: cuda
EMBEDDING_API_KEY=

# ---------- GPU / model download ----------
HF_TOKEN=
HF_HOME=/root/.cache/huggingface
OLLAMA_MAX_LOADED_MODELS=1         # บังคับ ไม่ใช่ทางเลือก — 6GB โหลดสองโมเดลไม่ได้
OLLAMA_KEEP_ALIVE=5m
OLLAMA_NUM_PARALLEL=1

# ---------- Datastores ----------
POSTGRES_USER=rag
POSTGRES_PASSWORD=
POSTGRES_DB=rag
DATABASE_URL=postgresql+asyncpg://rag:changeme@postgres:5432/rag
REDIS_URL=redis://redis:6379/0

# ---------- โควตา ----------
QUOTA_TIMEZONE=Asia/Bangkok
USER_DAILY_DOCUMENT_LIMIT=5
USER_DAILY_PAGE_LIMIT=500
USER_MAX_PAGES_PER_DOCUMENT=200
ADMIN_UNLIMITED=true
CHARS_PER_PAGE_ESTIMATE=3000

# ---------- Retrieval ----------
RETRIEVAL_TOP_K=8
RETRIEVAL_MIN_SCORE=0.35
CHUNK_SIZE=800
CHUNK_OVERLAP=120

# ---------- App / Auth ----------
APP_SECRET_KEY=
ADMIN_EMAIL=
ADMIN_PASSWORD=
CORS_ALLOWED_ORIGINS=http://localhost:3000
PUBLIC_API_URL=http://localhost:8000
```

---

## 8. ระบบโควตา (requirement ข้อ 3)

**กติกา:** user = 5 เอกสาร/วัน **และ** 500 หน้า/วัน (ทั้งสองเงื่อนไข) · admin = ไม่จำกัด

### 8.1 ต้องนับหน้า **ก่อน** เข้าคิว
ถ้ารอนับหลัง OCR = ปล่อยให้เผา GPU ไป 3 ชั่วโมงแล้วค่อยบอกว่าเกินโควตา

| ชนิดไฟล์ | นับหน้ายังไง (ก่อนเข้าคิว) |
|---|---|
| PDF | `pypdf.PdfReader(f).pages` — ถูกมาก ไม่ต้อง render |
| รูปภาพ | 1 หน้า |
| docx / txt / html | ไม่มีหน่วยหน้า → parse ข้อความ (เร็ว ไม่ใช้ GPU) แล้ว `ceil(chars / CHARS_PER_PAGE_ESTIMATE)` |

### 8.2 Reserve → commit → release
1. **Reserve** ตอน upload: นับหน้า → เช็คคงเหลือ → `+1 doc`, `+n pages` ทันที แล้วเข้าคิว
2. **Commit** เมื่อสำเร็จ: ปรับเป็นจำนวนหน้าจริง (เผื่อ estimate ของ docx คลาด)
3. **Release** เมื่อ job fail หรือ user ลบในวันเดียวกัน — **ไม่คืนถ้าผ่าน OCR ไปแล้ว** เพราะ GPU ถูกใช้ไปจริง (กันอัป-ลบ-อัปวนไม่จบ)

ทำใน transaction เดียวกับ `SELECT … FOR UPDATE` บนแถว `usage_counters` กัน race ตอนอัปหลายไฟล์พร้อมกัน

### 8.3 รายละเอียดที่มักลืม
- **`usage_date` เก็บเป็นวันที่ตาม `Asia/Bangkok`** ไม่ใช่ UTC ไม่งั้นโควตารีเซ็ตตอน 7 โมงเช้า
- **`USER_MAX_PAGES_PER_DOCUMENT`** ต้องมี ไม่งั้นไฟล์ 500 หน้าไฟล์เดียวยึดคิว GPU ทั้งวัน (บน 3050 = 4 ชั่วโมง)
- ตอบ **429** พร้อม body บอกยอดคงเหลือและเวลารีเซ็ต
- UI ต้องโชว์ยอดคงเหลือ **ก่อน** เลือกไฟล์ และโชว์ **คิวรอ + เวลาที่คาดว่าจะเสร็จ** เพราะบน 3050 รอเป็นชั่วโมง
- แยกคิว Celery เป็น `ocr_user` / `ocr_admin` — งาน bulk ของ admin จะได้ไม่ดองงาน user

### 8.4 ผลต่อสถาปัตยกรรมเดิม
ไดอะแกรมวาง Ingestion ไว้ใต้ Admin dashboard แต่โควตา "ต่อ user" แปลว่า user ทั่วไปอัปโหลดได้ → ต้องมี role model จริง

| role | อัปโหลด | เห็นเอกสาร | Playground | Analytics |
|---|---|---|---|---|
| `user` | ตามโควตา | เฉพาะของตัวเอง | ✗ | ✗ |
| `admin` | ไม่จำกัด | ทั้งหมด | ✓ | ✓ |

---

## 9. Data model (PostgreSQL)

| ตาราง | สาระ |
|---|---|
| `users` | email, bcrypt hash, role (`user`/`admin`), is_active |
| `documents` | owner_id, ชื่อ, MIME, path, สถานะ, collection, page_count, page_count_estimated |
| `usage_counters` | **(user_id, usage_date) unique** — documents_used, pages_used, pages_reserved |
| `quota_events` | audit: user_id, document_id, action (`reserve`/`commit`/`release`), delta_docs, delta_pages |
| `ingestion_jobs` | document_id, stage (`detect→ocr/parse→chunk→embed→done`), progress, error, timing, gpu_seconds |
| `chunks` | document_id, ordinal, text, page_no, token_count, `embedding vector(1024)`, metadata jsonb |
| `chat_sessions` | session_id, channel (`widget`/`playground`), user agent |
| `chat_messages` | session_id, role, content, latency_ms, prompt/completion tokens, model, prompt_config_id |
| `message_citations` | message_id, chunk_id, score, rank |
| `feedback` | message_id, rating (+1/−1), comment |
| `prompt_configs` | ชื่อ, system_prompt, top_k, temperature, is_active |

**Index:** HNSW `(embedding vector_cosine_ops)` บน `chunks`, GIN บน metadata jsonb, unique บน `(user_id, usage_date)`

---

## 10. API surface

**Public (chat widget)**
- `POST /api/chat` — SSE streaming → token stream + citations event
- `POST /api/feedback` · `GET /api/widget/config`

**ผู้ใช้ที่ล็อกอิน**
- `GET  /api/me/quota` — `{documents:{used,limit}, pages:{used,limit}, resets_at}`
- `POST /api/documents` — upload → นับหน้า → reserve → คืน `job_id` (หรือ **429** พร้อมยอดคงเหลือ)
- `GET  /api/documents` · `GET /{id}` · `DELETE /{id}`
- `GET  /api/jobs/{id}` — สถานะ + ตำแหน่งในคิว + ETA

**Admin เท่านั้น**
- `POST /api/admin/documents/bulk` — ไม่นับโควตา
- `POST /api/admin/documents/{id}/reprocess` — OCR ใหม่ด้วย `task_type` อื่น
- `POST /api/admin/playground/query` — คืนคำตอบ **พร้อม chunk + score ดิบ** ปรับ top_k/prompt ต่อ request ได้
- `GET/POST /api/admin/prompt-configs`
- `GET  /api/admin/analytics/*` · `GET /api/admin/quota/usage`

---

## 11. รายละเอียดทางเทคนิคที่ต้องระวัง

### 11.1 ตรวจสอบประเภทไฟล์ — ตัดสิน**รายหน้า**
PDF มี 3 แบบ: text layer เต็ม / สแกนล้วน / **ผสม** (พบบ่อยสุดในเอกสารไทย)
→ วนทีละหน้า ถ้าหน้าไหน `extract_text()` ได้ < ~50 ตัวอักษร ส่งเฉพาะหน้านั้นเข้า OCR ที่เหลือ parse ตรง
**บน 3050 ข้อนี้สำคัญที่สุดในเอกสารทั้งฉบับ** — PDF 100 หน้าที่มี text layer 80 หน้า ลดเวลาจาก 45 นาทีเหลือ 9 นาที
ใช้ `python-magic` เช็ค MIME จริง ไม่เชื่อนามสกุล

### 11.2 เรียก typhoon-ocr ให้ถูก
- **1.5-2b** (แนะนำสำหรับ tier local): เป็น single-prompt **ไม่ต้องใช้ anchor text แล้ว** เรียก `ocr_document("f.png", model="typhoon-ocr")`
- **7b** (รุ่นเก่า): ทำงานได้เฉพาะ prompt ที่ฝัง metadata จาก `get_anchor_text()` — เขียน prompt เองจะเพี้ยนแบบเงียบ ๆ
- ⚠️ หน้า model card อ้างทั้ง namespace `typhoon-ai/` และ `scb10x/` ให้ยืนยันตัวที่ใช้จริงในเฟส 0
- `task_type`: `default` เอกสารทั่วไป · `structure` เมื่อมีตาราง/ฟอร์ม

### 11.3 Chunking ภาษาไทย
ไทยไม่มีช่องว่างระหว่างคำ splitter default จะตัดกลางคำ
→ ตัดตามลำดับ: heading → ย่อหน้า (`\n\n`) → ประโยคด้วย `pythainlp.tokenize.sent_tokenize` → ค่อยตัดตามตัวอักษร
นับ token ด้วย tokenizer ของ bge-m3 ไม่ใช่จำนวนตัวอักษร และแนบ context หัวเอกสาร/หัวข้อไว้ต้น chunk

### 11.4 ทำความสะอาดหลัง OCR
ตัด header/footer ที่ซ้ำทุกหน้า, เลขหน้าโดด ๆ, `pythainlp.util.normalize` แก้สระ/วรรณยุกต์ซ้อน, ยุบช่องว่างและ soft hyphen

### 11.5 Retrieval
- เฟส 1: vector search (cosine) + `RETRIEVAL_MIN_SCORE` cutoff — ไม่มี chunk ผ่าน = ตอบ "ไม่พบข้อมูล" **ห้ามให้ LLM เดา** (สำคัญขึ้นอีกกับโมเดล 4B ที่ hallucinate ง่ายกว่า 27B)
- เฟส 2: hybrid = vector + keyword (tsvector tokenize ด้วย pythainlp) รวมด้วย Reciprocal Rank Fusion
- เฟส 3: rerank ด้วย `bge-reranker-v2-m3` — retrieve 30 → เหลือ 8 (รันบน CPU ได้)
- role `user` ต้อง filter `owner_id` **ที่ระดับ SQL** ไม่ใช่กรองหลัง search

### 11.6 ชดเชยคุณภาพเมื่อใช้โมเดล 4B
โมเดลเล็กอ่อนเรื่องสังเคราะห์หลายแหล่ง แต่ RAG ช่วยได้เยอะเพราะงานหลักคือสรุปจาก context ไม่ใช่ world knowledge → ทุ่มน้ำหนักไปที่ **retrieval quality** แทน:
เปิด rerank ตั้งแต่แรก · ลด `top_k` เหลือ 4–5 (context สั้น โมเดลเล็กโฟกัสดีกว่า) · prompt สั้นและสั่งตรง ๆ · บังคับ citation ทุกประโยค

### 11.7 Prompt & thinking mode
System prompt บังคับ: ตอบจาก context เท่านั้น · อ้างอิง `[1] [2]` ที่ map กลับ chunk_id · ตอบภาษาเดียวกับคำถาม
ปิด thinking สำหรับ chat ปกติ (`LLM_ENABLE_THINKING=false`) เปิดเฉพาะใน Playground ไว้ debug — บนการ์ดช้า thinking ทำให้รอเป็นนาที

### 11.8 ความปลอดภัย
- widget endpoint: rate limit ด้วย Redis ต่อ IP + origin allowlist
- JWT ใน httpOnly cookie, ปิด `/api/admin/*` ที่ Caddy ด้วยถ้าเปิด public
- **ห้ามเปิดพอร์ต Ollama / vLLM ออกอินเทอร์เน็ต** — ไม่มี auth ในตัว ใครยิงถึงก็ใช้ GPU ได้ฟรี
- ไฟล์อัปโหลด: จำกัดขนาด, ตรวจ MIME, เก็บนอก web root

---

## 12. โครงสร้าง repo

```
RAG_Workshop/
├── docker-compose.yml
├── docker-compose.local.yml          # Ollama tier
├── docker-compose.gpu.yml            # vLLM tier
├── docker-compose.override.yml       # dev: hot reload
├── .env.example
├── caddy/Caddyfile
├── api/
│   ├── Dockerfile                    # + poppler-utils, libmagic1
│   ├── pyproject.toml
│   ├── alembic/
│   └── app/
│       ├── main.py            routers/  schemas/  models/
│       ├── core/              config.py  security.py  deps.py
│       ├── quota/             service.py  middleware.py  page_count.py
│       ├── ingestion/         detect.py  ocr_typhoon.py  parsers.py
│       │                      clean.py   chunk.py   embed.py  tasks.py
│       ├── retrieval/         vector_store.py  search.py  rerank.py
│       └── llm/               client.py  prompts.py  orchestrator.py
└── web/
    ├── Dockerfile
    └── src/app/(app)/documents | (admin)/playground | analytics
        src/widget/                   # bundle แยกเป็น widget.js
```

---

## 13. แผนงานเป็นเฟส

### สถานะปัจจุบัน (อัปเดต 6 ก.ย. 2026)

| เฟส | สถานะ | หมายเหตุ |
|---|---|---|
| 0. Spike โมเดล | ✅ **ผ่าน** | OCR **5.2 วิ/หน้า** + แปลงตารางเป็น HTML · chat **19–28 วิ/คำตอบ** · ทั้งคู่ `100% GPU` |
| 1. Skeleton | ✅ เสร็จ | compose ครบ · migration 0001+0002 · `/health/deep` |
| 2. Auth + Quota | ✅ เสร็จ | login/JWT · reserve→commit→release · `GET /api/me/quota` · 429 พร้อมยอดคงเหลือ |
| 3. Ingestion | ✅ **ทดสอบจริงผ่านทั้งสองเส้นทาง** | ไฟล์ข้อความจบใน 3 วิ · ภาพผ่าน OCR จบใน 6.7 วิ · `processor_note` บันทึก `100% GPU` ถูกต้อง |
| 4. Retrieval + Chat | ✅ **ทดสอบกับโมเดลจริงแล้ว** | ถามไทย → ตอบไทยพร้อมอ้างอิง `[1]` ที่ชี้กลับไปเอกสารที่ผ่าน OCR ได้ถูกต้อง |
| 5. Playground | ✅ เสร็จ | query เห็น chunk + score ดิบ · โหมด retrieval-only · prompt config + activate |
| 6. Analytics | ✅ เสร็จ | overview/unanswered/documents/ingestion/quota usage |
| 7. Hardening | ✅ เกือบครบ | rate limit · hybrid search (hit@1 88%→100%) · eval set 25 ข้อ · backup · reprocess · bulk upload · เหลือ rerank ที่ยังไม่มีหลักฐานว่าจำเป็น |

**เทสทั้งหมด 167 ตัวผ่าน** (unit + integration ที่ยิงใส่ PostgreSQL จริง)
รันด้วย `.\dc.ps1 exec api pytest -q`

**ฝั่ง web ครบแล้ว** — Login, Documents (อัปโหลด + โควตา + progress), Chat (SSE + citation +
feedback), Playground (admin), Analytics (admin), สถานะระบบ

**ทดสอบ ingestion เต็มสายแล้วด้วยไฟล์ข้อความ** (8 ก.ย. 2026)
upload → นับหน้า → หักโควตา → parse → clean → chunk → embed → เก็บลง DB จบใน 3 วินาที
ได้ 3 chunk แยกตามหัวข้อ มี embedding ครบ token count จริงจาก TEI
และ retrieval คืน chunk ถูกต้องอันดับ 1 ที่คะแนน 0.79
**เหลือเฉพาะเส้นทาง OCR ที่ยังทดสอบไม่ได้เพราะโมเดลยังโหลดไม่เสร็จ**

### แผนเดิม

| เฟส | ส่งมอบ | ประเมิน |
|---|---|---|
| **0. Spike โมเดลบน 3050** | ยืนยัน GGUF ของ typhoon-ocr1.5-2b ใช้ได้จริงบน Ollama, OCR หน้าไทย 1 หน้าอ่านออก, จับเวลาจริง/หน้า, chat ผ่าน `/v1/chat/completions` ได้ | 0.5 วัน |
| **1. Skeleton** | compose ขึ้นครบ, `/health` เขียว, alembic migration แรก, pgvector extension | 0.5 วัน |
| **2. Auth + Quota** | สมัคร/ล็อกอิน, role user/admin, `usage_counters` + reserve/commit/release, `GET /api/me/quota`, 429 ถูกต้อง | 1 วัน |
| **3. Ingestion** | upload → นับหน้า → detect รายหน้า → OCR/parse → clean → chunk → embed ผ่าน Celery, หน้า Documents + progress + ETA | 2.5 วัน |
| **4. Retrieval + Chat** | `/api/chat` SSE พร้อม citation, chat widget ใช้ได้จริง, scoping ตาม role | 1.5 วัน |
| **5. Playground** | ยิง query เห็น chunk + score, ปรับ prompt/top_k/temperature/thinking, save เป็น prompt_config | 1 วัน |
| **6. Analytics** | log ทุก turn, dashboard latency/feedback/คำถามที่ตอบไม่ได้ + หน้าโควตารายคน | 1 วัน |
| **7. Hardening** | rate limit, hybrid search + rerank, eval set ~50 คำถามวัด hit-rate, backup pg_dump | 1.5 วัน |

**เฟส 0 ต้องทำก่อนเสมอ** — ถ้า GGUF ของ typhoon-ocr1.5-2b ยังไม่รองรับ vision บน Ollama ต้องรู้ตั้งแต่วันแรก ไม่ใช่ไปเจอตอนเฟส 3

**Fallback ถ้าเฟส 0 ไม่ผ่าน:** รัน typhoon-ocr1.5-2b BF16 ผ่าน vLLM ใน WSL2 ด้วย `--max-model-len 8192 --gpu-memory-utilization 0.85` (2B BF16 ≈ 4GB ยังพอลง 6GB ได้ถ้าไม่โหลด LLM พร้อมกัน) หรือใช้ transformers ตรง ๆ ใน worker

**Definition of done เฟส 3:** อัป PDF สแกนไทย 20 หน้า → เห็น chunk ที่อ่านออกใน DB ภายใน ~10 นาที ไม่มี job ค้าง โควตาถูกหักเป็น 1 เอกสาร / 20 หน้า

---

## 14. บันทึกการตัดสินใจ

| # | เรื่อง | สรุป |
|---|---|---|
| 1 | Model tier | **Tier LOCAL เป็น production** — RTX 3050 6GB คือเครื่องจริง ไม่ใช่แค่ dev |
| 2 | Chat model | `Qwen3.5-4B` Q4 (Qwen3.8-27B รันบนการ์ดนี้ไม่ได้ และ Qwen3.8 ไม่มีรุ่นเล็ก) |
| 3 | OCR model | `scb10x/typhoon-ocr1.5-3b` จาก Ollama registry — รุ่น 1.5 เลิกใช้ anchor text แล้ว และดาวน์โหลดเร็วกว่า HF สิบเท่า |
| 4 | Runtime | **Ollama ในคอนเทนเนอร์** ไม่ใช่ vLLM — auto load/unload จำเป็นบน 6GB · รันทุกอย่างผ่าน Docker ไม่ต้องลง Python/Ollama บน Windows |
| 5 | สเกล | ระดับ workshop, จำนวน user ยังไม่แน่ → **ออกแบบให้ scale ได้ แต่ยังไม่ optimize** |

### 14.1 "ออกแบบให้ scale ได้ แต่ไม่ optimize" แปลว่าอะไรในทางปฏิบัติ

**ทำตั้งแต่แรก** (ราคาถูกตอนนี้ แพงมากถ้าย้อนมาแก้ทีหลัง)
- ทุก model endpoint อ่านจาก `.env` — ย้ายไป Tier MID/PROD = แก้ 4 บรรทัด ไม่แตะโค้ด
- `VectorStore` เป็น interface — เปลี่ยน pgvector → Qdrant ได้โดยไม่ยุ่งกับ retrieval logic
- แยกคิว Celery เป็น `ocr_user` / `ocr_admin` ตั้งแต่วันแรก — เพิ่ม worker ทีหลังแค่เปลี่ยน scale
- เก็บ `gpu_seconds` ต่อ job ลง `ingestion_jobs` ตั้งแต่แรก — เป็นข้อมูลที่ใช้ตัดสินว่าเมื่อไหร่ต้องขยาย

**ยังไม่ทำ** (รอให้ analytics บอกก่อน)
- multi-GPU scheduling, model sharding, distributed worker
- caching layer ของ embedding/answer
- rerank (เปิดได้ทีหลังด้วย flag ถ้าคุณภาพคำตอบไม่พอ)

### 14.2 สัญญาณว่าถึงเวลาขยายฮาร์ดแวร์
ดูจาก dashboard เฟส 6 — เข้าเงื่อนไขข้อไหนก็ขยับไป Tier MID ได้เลย
- คิว OCR รอเกิน **8 ชั่วโมง** ติดกันเกิน 3 วัน
- user โดน 429 จากโควตาบ่อยกว่า 20% ของการอัปโหลด
- feedback เชิงลบเกิน 30% โดยที่ retrieval หา chunk ถูกแล้ว (= โมเดล 4B ไม่พอ ต้องขยับเป็น 9B/14B)

### 14.3 บทเรียนจากการติดตั้งจริง

**TEI ถูก OOM kill ที่ขั้น warmup ด้วยค่า default**
หลังโหลดโมเดลเสร็จ TEI จะ warm up ด้วย batch ขนาด `--max-batch-tokens` (default 16384)
และเปิด tokenization worker เท่าจำนวน CPU (11 ตัวบนเครื่องนี้) รวมกับโมเดล ONNX ~2.5GB
แล้วทะลุ RAM ของ WSL VM → โดน SIGKILL (exit 137) แล้ว restart วนไป **337 รอบ**
อาการหลอกตรงที่ไม่มี error log เลย (SIGKILL ไม่ทิ้งข้อความ) และ `.State.OOMKilled`
อ่านได้ `false` เพราะตอน inspect คอนเทนเนอร์กำลัง restart อยู่
แก้ด้วย `--max-batch-tokens 4096 --max-client-batch-size 16 --tokenization-workers 2`
→ warmup ผ่านใน 23 วินาที ใช้ RAM 3.7GB

**watcher ที่ grep แต่คำว่า error จะมองไม่เห็นการตายแบบนี้**
ต้อง grep `exited with code` ด้วยเสมอ ไม่งั้น crash loop จะดูเหมือน "ยังทำงานอยู่"

**TEI ต้อง pin ด้วย digest ไม่ใช่ tag**
`cpu-1.5` โหลด bge-m3 ไม่ได้เลย ล้มด้วย `relative URL without a base` เพราะ hf-hub 0.3.2
parse relative redirect ของ HF CDN ไม่ได้ — ไม่ใช่ปัญหาเครือข่าย (ยิง huggingface.co
จากในคอนเทนเนอร์ได้ HTTP 200 ปกติ) แก้ด้วยการขยับไป 1.9.3 แล้ว pin digest ไว้

**`${VAR:-}` ใน compose สร้าง env var ที่เป็นสตริงว่าง ไม่ใช่ไม่มี**
ตอนแรกเข้าใจว่า `HF_TOKEN=` ที่ว่างเป็นต้นเหตุ ซึ่งเดาผิด แต่การตัดออกก็ยังถูกอยู่ —
bge-m3 เป็น public model ไม่ต้องใช้ token และ env var ที่ว่างเปล่าสร้างปัญหาได้ในหลายเครื่องมือ

**`mapped_column(default=0)` ของ SQLAlchemy ไม่ใช่ default ตอนสร้าง object**
มันทำงานตอน INSERT เท่านั้น การสร้าง `UsageCounter()` ลอย ๆ เพื่อคืนค่าโควตาของ user
ที่ยังไม่มีแถวในตาราง จึงได้ `None` ทุกช่องแล้วพังทันที — ซึ่งเป็นเคสแรกสุดที่ทุกคนจะเจอ

**`pythainlp.util.normalize` ยุบบรรทัดว่างทิ้ง**
ถ้า normalize ทั้งก้อนก่อน chunk ขอบเขตย่อหน้าจะหายหมด แล้ว chunking ตกไปใช้
การตัดตามความยาวล้วน ต้อง normalize ทีละบรรทัดแทน

**`pycrfsuite` ไม่ได้ติดมากับ pythainlp**
`sent_tokenize(engine="crfcut")` จึงพังทันที ทำ fallback เป็น `whitespace+newline`
ซึ่งยังใช้ได้จริงเพราะช่องว่างในภาษาไทยทำหน้าที่คั่นประโยคอยู่แล้ว
ติดตั้ง `python-crfsuite` เมื่อไหร่ระบบจะสลับกลับไปใช้ crfcut เองโดยไม่ต้องแก้โค้ด

**`docker pull` ค้างได้ไม่จำกัดเวลา**
เมื่อการเชื่อมต่อขาดกลางคันมันไม่ error ออกมา ต้องครอบด้วย `timeout` เสมอ
(รอบแรกค้างไป 3 ชั่วโมงโดยไม่มีอะไรบอก)

**การโหลดโมเดล: อย่าใช้ `ollama pull` บนลิงก์ที่ไม่นิ่ง**
Ollama แบ่งไฟล์เป็นหลาย part พร้อมกัน แต่ละ part stall แล้ว retry วนไม่จบ
วัดได้ 23 KB/s (default) และ 47 KB/s (`OLLAMA_MAX_TRANSFER_STREAMS=1`)
ขณะที่ curl ดึงไฟล์เดียวกันได้ 372–546 KB/s
ทำได้เพราะ Ollama ตั้งชื่อ blob เป็น sha256 ของไฟล์ ตรงกับ `x-linked-etag` ที่ HF ประกาศไว้พอดี
→ `scripts/fetch-ollama-blob.sh` + `scripts/stage-ollama-blobs.sh`

**Ollama ลบ blob ที่ยังไม่มี manifest ทุกครั้งที่ start**
ไฟล์ที่โหลดค้างไว้หายหมดเมื่อ restart (เสียไป 122 MB) แก้ด้วย `OLLAMA_NOPRUNE=1`
และพักไฟล์ไว้ใน volume แยกก่อนย้ายเข้า blobs

**`curl -C -` ไม่พอสำหรับ resume — เสียของมาสองรอบ**
1. `--retry` ของ curl เริ่มใหม่จากไบต์ 0 เพราะ offset คำนวณครั้งเดียวตอนเริ่มโปรเซส
   (โหลดได้ 6 MB แล้วเหลือ 1 MB)
2. ต่อให้ retry อยู่นอก curl ถ้าเซิร์ฟเวอร์ตอบ 200 แทน 206 curl จะเขียนทับไฟล์ทันที
   (โหลดได้ 90 MB แล้วเหลือ 2.4 MB)
→ ต้องให้ curl เขียนลงไฟล์ชั่วคราว ตรวจ HTTP code เอง แล้วค่อย `cat >>` ต่อท้าย
   ไฟล์ปลายทางจึงมีแต่โตขึ้น และต้องมี lock กันสองโปรเซสทำพร้อมกัน

**ความเร็วไป HuggingFace แกว่ง 20 เท่าตามช่วงเวลา**
วัดได้ 6.8 KB/s ถึง 546 KB/s ที่ไฟล์เดียวกัน ขณะที่ GitHub ได้ 178 KB/s สม่ำเสมอ
→ **วัดความเร็วก่อนเริ่มโหลดใหญ่ทุกครั้ง** ถ้าช้าให้รอช่วงอื่นแทนการฝืน

**`min_score` ต้องวัด ไม่ใช่เดา**
ค่าเริ่มต้น 0.35 ที่ตั้งไว้ตอนแรกตกอยู่ในช่วงคะแนนของคำถามที่ *ไม่มี* คำตอบในเอกสาร
วัดกับ bge-m3 บนเอกสารไทยจริง: คำถามที่มีคำตอบได้ 0.67–0.79 ส่วนที่ไม่มีได้ 0.25–0.39
→ เปลี่ยนเป็น **0.5** ซึ่งอยู่กลางช่องว่าง · วัดซ้ำได้จาก Playground เมื่อเปลี่ยนโมเดล embedding

**Next.js dev บน bind mount ของ Windows ไม่เห็นไฟล์ใหม่**
inotify ไม่ส่ง event ข้ามจาก Windows เข้า WSL2 หน้าที่เพิ่มใหม่จะได้ 404 ทุกหน้า
แก้ด้วย `WATCHPACK_POLLING=true` และ `CHOKIDAR_USEPOLLING=true`

**typhoon-ocr ไม่ได้คืน markdown heading — chunker จึงแบ่งตามหัวข้อไม่ได้**
`chunk.py` ออกแบบให้ตัดตามหัวข้อ markdown (`#`) แต่ typhoon-ocr1.5 คืนข้อความธรรมดา
กับตาราง HTML (`<table>`) ไม่มี `#` เลย หน้าที่ผ่าน OCR จึงถูกแบ่งด้วยย่อหน้า/ความยาว
อย่างเดียว และไม่ได้ prefix ชื่อหัวข้อเข้าไปใน chunk
ยังไม่กระทบตอนนี้เพราะหน้าเดียวสั้นกว่า `CHUNK_SIZE` แต่หน้าที่ยาวและมีหลายเรื่อง
จะได้ chunk ที่ปนกัน → **ถ้า retrieval แม่นไม่พอ ให้แก้ที่นี่ก่อน** เช่น จับรูปแบบ
`ข้อ N` / `หมวด N` เป็นขอบเขตหัวข้อเพิ่ม

**`chat_template_kwargs` ปิด thinking ของ Ollama ไม่ได้ — เป็นของ vLLM**
อาการที่ผู้ใช้เจอ: ถามแล้วหน้าจอนิ่ง 20–37 วินาที จนคิดว่าระบบค้างแล้วถามซ้ำ
เดาผิดสองรอบว่าเป็นเรื่องโหลดโมเดลกับ prefill จนไปวัด token จริงถึงเห็นว่า
คำถาม "1+1 เท่ากับเท่าไหร่" สร้าง reasoning ซ่อนไว้ **3,307 token ใช้เวลา 86 วินาที**
ขณะที่ prefill ใช้แค่ 0.3 วินาที — Ollama เพิกเฉยฟิลด์นั้นมาตลอดโดยไม่มี error
→ ต้องส่ง `reasoning_effort: "none"` ด้วย · ผลคือ token แรกจาก 20–37 วิ เหลือ **0.3–1.3 วิ**
→ **บทเรียน: เวลาปรับ inference ให้ดู token count จริง อย่าเดาจากเวลาที่ใช้**

**`docker compose build` ไม่อัปเดต node_modules ในโหมด dev**
`docker-compose.override.yml` ผูก `/app/node_modules` เป็น anonymous volume เพื่อกัน
ไม่ให้ bind mount จาก Windows ไปทับ แต่ volume นั้นค้างจากตอนสร้าง container ครั้งแรก
และทับ node_modules ของ image ใหม่ — build แล้ว `package.json` เปลี่ยนก็ไม่มีผล
(เจอมาแล้ว: build เสร็จแต่ยังรัน Next 15.1.6 ทั้งที่ package.json เป็น 16.3.4)
→ ต้องใช้ `docker compose up -d --force-recreate --renew-anon-volumes web`
   ซึ่งล้างเฉพาะ anonymous volume ไม่แตะ named volume ที่เก็บข้อมูลจริง

**ไฟล์ `.ps1` ที่มีภาษาไทยต้องบันทึกเป็น UTF-8 with BOM**
PowerShell 5.1 อ่านไฟล์เป็น ANSI ถ้าไม่มี BOM แล้วสตริงภาษาไทยจะพังจน parse ไม่ผ่าน
และห้ามตั้ง `$ErrorActionPreference = 'Stop'` ในสคริปต์ที่เรียก docker เพราะ docker
เขียนความคืบหน้าปกติลง stderr แล้ว PowerShell จะตีเป็น error

**ความช้าตอนโหลดโมเดลไม่ใช่ "เน็ตช้า" เสมอไป — ต้องแยกให้ออกก่อนแก้**
วัดพร้อมกันในนาทีเดียวกันจากเครื่องเดียวกัน: HuggingFace 6.8 KB/s · GitHub 178 KB/s ·
Ollama registry 315–500 KB/s ปัญหาอยู่ที่เส้นทางไปปลายทางบางแห่ง ไม่ใช่แบนด์วิดท์ของบ้าน
ก่อนจะไปปรับ tuning อะไร ให้ probe ปลายทางหลาย ๆ ที่เทียบกันก่อนเสมอ

**`OLLAMA_MAX_TRANSFER_STREAMS=1` ช่วยเรื่อง stall ได้จริง**
ค่า default 4 stream ทำให้เกิด "part N stalled; retrying" ถี่มาก (201 ครั้งใน 400 บรรทัด)
ตั้งเป็น 1 แล้ว stall เหลือ 0 และความเร็วขึ้นเท่าตัว

**`OLLAMA_NOPRUNE=1` จำเป็นถ้าจะยุ่งกับ blob เอง**
Ollama ลบ blob ที่ยังไม่มี manifest อ้างถึงทุกครั้งที่ start — restart ทีเดียวหายไป 122 MB

**`curl -C -` ไม่พอสำหรับ resume บนลิงก์ที่ขาดบ่อย** (เสียของสองรอบกว่าจะรู้)
1. `--retry` ของ curl เริ่มใหม่จากไบต์ 0 เพราะ offset ถูกคำนวณครั้งเดียวตอนเริ่มโปรเซส
2. ต่อให้ย้าย retry ออกมาข้างนอก ถ้าเซิร์ฟเวอร์ตอบ 200 แทน 206 curl จะเขียนทับตั้งแต่ต้น
วิธีที่ปลอดภัยคือให้ curl เขียนลงไฟล์ชั่วคราว ตรวจ HTTP code เอง แล้วค่อย append
(ดู `scripts/fetch-ollama-blob.sh` — เก็บไว้เป็นทางสำรองถ้าต้องดึงจาก HF อีก)

### 14.4 ที่ยังค้าง
1. **user เห็นเอกสารของกันและกันไหม** — default คือเห็นเฉพาะของตัวเอง ถ้าอยากเป็นคลังกองกลางต้องแก้ retrieval scoping (ข้อ 11.5) **ตอบก่อนเฟส 3**
2. **เปิดให้เข้าจากภายนอกไหม** — ถ้าเปิด ต้องทำ Caddy + โดเมน + TLS ถ้าใช้ในวงแลนอย่างเดียวก็ข้ามไปได้ **ตอบก่อนเฟส 7**

---

## 15. ความพร้อมของเครื่อง

ตรวจแล้ว — **รันทุกอย่างผ่าน Docker ได้ ไม่ต้องลงอะไรเพิ่มบน Windows**

| รายการ | สถานะ |
|---|---|
| Docker Engine 29.4.3 (WSL2 backend, linux) | ✅ daemon ทำงานแล้ว |
| WSL2 default version 2, distro `docker-desktop` running | ✅ |
| NVIDIA driver 560.94, RTX 3050 6GB, compute 8.6 | ✅ |
| RAM 16 GB (WSL VM ได้ 8.26 GB) | ⚠️ ควรตั้ง `.wslconfig` เป็น 10 GB (ดูข้อ 6.2) |
| ดิสก์ว่าง 97.5 GB | ✅ |
| Node v22.14.0, Git | ✅ (ไม่จำเป็นแล้ว แต่มีไว้สะดวก) |
| Python บน Windows | ➖ **ไม่ต้องลง** — อยู่ใน image ของ `api`/`worker` |
| Ollama บน Windows | ➖ **ไม่ต้องลง** — เป็นคอนเทนเนอร์ |
| poppler | ➖ **ไม่ต้องลง** — อยู่ใน image ของ `api`/`worker` |

**สิ่งเดียวที่ต้องทำเอง:** สร้าง `C:\Users\PC\.wslconfig` ตามข้อ 6.2 แล้วสั่ง `wsl --shutdown` หนึ่งครั้ง

**พื้นที่ที่จะใช้:** model weights ~5 GB (ใน named volume `ollama-models`) + Docker images ~8 GB

### 15.1 คำสั่งประจำวัน
```powershell
docker compose up -d                        # ขึ้นทั้ง stack
docker compose logs -f worker               # ดู log งาน OCR
docker compose exec api alembic upgrade head  # migration
docker compose exec api pytest              # เทส
docker compose exec ollama ollama list      # ดูโมเดลที่โหลดไว้
docker stats                                # ดู RAM ต่อคอนเทนเนอร์
```
ไม่มีคำสั่งไหนต้องใช้ Python หรือ Ollama บน Windows เลย
