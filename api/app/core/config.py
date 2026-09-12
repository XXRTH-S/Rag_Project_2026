from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        # ชื่อ field อย่าง model_tier / llm_model ชนกับ namespace ที่ pydantic สงวนไว้
        protected_namespaces=(),
    )

    # ---------- tier ----------
    model_tier: str = "local"

    # ---------- LLM ----------
    llm_base_url: str = "http://ollama:11434/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen3.5:4b"
    llm_max_model_len: int = 8192
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024
    llm_timeout_seconds: int = 180
    llm_enable_thinking: bool = False
    # ค่าที่ส่งไปกับ reasoning_effort เมื่อปิด thinking
    # "none" ใช้ได้กับ Ollama · ผู้ให้บริการบางเจ้าอาจรับแค่ "low"/"minimal"
    # ตั้งเป็นค่าว่างเพื่อไม่ส่งฟิลด์นี้เลย ถ้าเจอ provider ที่ปฏิเสธ
    llm_reasoning_effort: str = "none"

    # ---------- LLM สำรอง ----------
    # ลำดับการเรียก: ตัวหลัก (LLM_*) -> ตัวสำรอง (LLM_FALLBACK_*) -> ยกข้อความจากเอกสาร
    #
    # ใช้เมื่ออยากให้ API เป็นหลักและโมเดลในเครื่องเป็นตัวสำรองเวลา key มีปัญหา
    # (หมดโควตา โดน rate limit เน็ตล่ม) หรือกลับกันก็ได้ แค่สลับค่าสองชุดนี้
    # เว้น base_url ว่างเพื่อปิดตัวสำรอง
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    # หยุดเรียกตัวหลักชั่วคราวหลังล้มติดกันกี่ครั้ง — กันไม่ให้ทุกคำถามต้องรอ timeout
    llm_breaker_threshold: int = 3
    llm_breaker_cooldown_seconds: int = 120
    # เมื่อเรียก LLM ไม่ได้ (ยังไม่ได้ pull โมเดล / บริการล่ม) ให้ยกข้อความจากเอกสาร
    # ที่ค้นเจอมาแสดงแทนการโยน error ใส่ผู้ใช้ — ระบบยังมีประโยชน์แม้โมเดลไม่พร้อม
    # ตั้ง false ถ้าอยากให้ล้มดัง ๆ เพื่อไม่ให้ปัญหาถูกกลบ
    llm_fallback_to_excerpts: bool = True
    # โหลดโมเดลเข้า VRAM ตอน API เริ่ม เพื่อให้คำถามแรกไม่ต้องรอ 21 วินาที
    # ปิดได้ถ้าไม่อยากให้ VRAM ถูกจองไว้ตั้งแต่เปิดเครื่อง
    llm_warmup_on_start: bool = True

    # ---------- OCR ----------
    typhoon_ocr_base_url: str = "http://ollama:11434/v1"
    typhoon_ocr_api_key: str = ""
    typhoon_ocr_model: str = "typhoon-ocr"
    typhoon_ocr_task_type: str = "default"
    typhoon_ocr_concurrency: int = 1
    typhoon_ocr_page_timeout: int = 120
    # หน้าที่ text layer ให้ตัวอักษรน้อยกว่านี้ ถือว่าเป็นหน้าสแกน ต้องส่งเข้า OCR
    # เอกสารไทยส่วนใหญ่เป็น PDF ผสม การตัดสินรายหน้าจึงประหยัดเวลามหาศาล
    ocr_min_chars_per_page: int = 50
    # ใช้คำนวณ ETA ให้ user เห็นก่อนกดอัปโหลด
    # วัดจริงบน RTX 3050 + typhoon-ocr1.5-2b Q4 (8 ก.ย. 2026): 5.2 วิ/หน้า ที่ 72.7 tok/s
    # แต่หน้าที่วัดเป็นภาพเรนเดอร์สะอาด สแกนจริงมี noise/เอียง/ลายมือ จะช้ากว่านี้
    # จึงตั้ง 10 เผื่อไว้ — ค่าจริงดูได้จาก /api/admin/analytics/ingestion (seconds_per_page)
    ocr_seconds_per_page: float = 10.0
    # งานที่เข้าคิวไว้แต่ไม่เคยถูกหยิบไปทำนานเกินนี้ ถือว่า worker ตายไปแล้ว
    # แล้วปล่อยให้ admin สั่งประมวลผลใหม่ได้ ไม่งั้นเอกสารนั้นค้างถาวร
    # ตั้งสูงกว่าเวลารอคิวจริงที่ยาวที่สุดที่ยอมรับได้ — คิวยาวไม่ใช่คิวตาย
    ingestion_stale_after_minutes: int = 30

    # ---------- Embedding ----------
    embedding_base_url: str = "http://embeddings:8080"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_device: str = "cpu"
    embedding_api_key: str = ""

    # ---------- Datastores ----------
    database_url: str = "postgresql+asyncpg://rag:changeme@postgres:5432/rag"
    redis_url: str = "redis://redis:6379/0"

    # ---------- Quota ----------
    quota_timezone: str = "Asia/Bangkok"
    user_daily_document_limit: int = 5
    user_daily_page_limit: int = 500
    user_max_pages_per_document: int = 200
    admin_unlimited: bool = True
    chars_per_page_estimate: int = 3000

    # ---------- Retrieval ----------
    # วัดกับ qwen3.5:4b บน RTX 3050 (9 ก.ย. 2026) คำถามเดียวกัน คำตอบถูกทุกค่า:
    #   top_k=8 -> 28.5 วิ · top_k=4 -> 23.8 วิ · top_k=2 -> 19.2 วิ
    # เวลาส่วนใหญ่หมดไปกับ prefill ของ context ไม่ใช่การ generate
    # เลือก 5 เพราะ eval ได้ hit@1 100% ที่ค่านี้ (ดู scripts/eval.py) และเร็วกว่า 8
    retrieval_top_k: int = 5
    # วัดกับ bge-m3 บนเอกสารไทยจริง (8 ก.ย. 2026):
    #   คำถามที่มีคำตอบในเอกสาร  0.67-0.79
    #   คำถามที่ไม่มีคำตอบ        0.25-0.39
    # ค่าเดิม 0.35 ตกอยู่ในช่วงของกลุ่มที่ไม่เกี่ยว ทำให้ chunk ที่ไม่เกี่ยวหลุดไปถึง LLM
    # 0.5 อยู่กลางช่องว่างระหว่างสองกลุ่ม — วัดซ้ำได้จาก Playground เมื่อเปลี่ยนโมเดล embedding
    retrieval_min_score: float = 0.5
    # เปิดใช้ keyword leg ร่วมกับ vector (RRF)
    # วัดกับ evalsets/hr.json (8 ก.ย. 2026): hit@1 88% -> 100%, MRR 0.882 -> 1.000
    # ช่วยมากกับคำถามเชิงโครงสร้าง ("ข้อ 3 พูดถึงอะไร", "ประกาศออกเมื่อไหร่")
    # ซึ่ง dense retrieval หาไม่เจอเพราะความหมายทับกับเนื้อหาน้อย
    retrieval_hybrid: bool = True
    # เกณฑ์สำหรับ chunk ที่ keyword หาเจอแต่ vector ไม่เจอ — ต่ำกว่า min_score ได้
    # เพราะการตรงคำเป็นหลักฐานเพิ่มเติม แต่ยังต้องกัน chunk ที่ไม่เกี่ยวเลย
    #
    # ปรับจาก 0.35 เป็น 0.40 หลังเติมคลังด้วยเอกสารคนละหมวด (9 ก.ย. 2026)
    # คลังหลายหมวดทำให้คำไปซ้ำข้ามเรื่องกันเอง เช่นคำถาม "นโยบายการทำงานจากที่บ้าน"
    # ไปตรงกับหัวข้อ "การทำงานแบบอะซิงโครนัส" ของ JavaScript ที่คะแนน 0.356
    #
    # วัดกับ evalsets/hr.json บนคลัง 85 chunk ที่มีทั้ง HR และคู่มือเขียนโปรแกรม:
    #   0.35 -> hit@1 100% · ปฏิเสธถูก 50%
    #   0.40 -> hit@1 100% · ปฏิเสธถูก 62%   <- เลือกค่านี้ ดีขึ้นโดยไม่เสียอะไร
    #   0.45 -> hit@1  94% · ปฏิเสธถูก 75%   เริ่มแลกคำตอบที่หาเจอทิ้ง
    # ไม่ดันไปถึง 0.45 เพราะชั้น LLM ปฏิเสธ chunk ที่ไม่เกี่ยวได้อยู่แล้ว
    # การหาคำตอบไม่เจอเสียหายกว่าการส่ง chunk อ่อน ๆ ให้โมเดลอ่านแล้วมันปฏิเสธเอง
    retrieval_keyword_floor: float = 0.40
    chunk_size: int = 800
    chunk_overlap: int = 120

    # ---------- App ----------
    app_secret_key: str = "dev-only-change-me"
    admin_email: str = ""
    admin_password: str = ""
    cors_allowed_origins: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 50
    access_token_expire_minutes: int = 60 * 12
    # False สำหรับ http://localhost ตอน dev — ต้องตั้งเป็น true เมื่อเปิด HTTPS จริง
    # ไม่งั้น browser จะส่ง cookie ผ่าน http ธรรมดาได้
    cookie_secure: bool = False

    # ---------- บุคลิกของผู้ช่วย ----------
    # คำลงท้ายสุภาพภาษาไทย — "ครับ" หรือ "ค่ะ" แล้วแต่บุคลิกที่องค์กรเลือก
    # ตั้งเป็นค่าว่างถ้าไม่ต้องการคำลงท้าย (เช่น ใช้กับผู้ใช้ต่างชาติเป็นหลัก)
    bot_polite_particle: str = "ครับ"

    # ---------- Chat widget ----------
    widget_title: str = "ผู้ช่วยตอบคำถาม"
    # ใช้ "เรา" ให้ตรงกับสรรพนามที่สั่งไว้ใน system prompt
    # ไม่งั้นข้อความต้อนรับกับคำตอบจะเรียกตัวเองคนละแบบในบทสนทนาเดียว
    widget_greeting: str = "ถามอะไรก็ได้เกี่ยวกับเอกสารในระบบ เราจะตอบพร้อมอ้างอิงที่มาให้"
    widget_accent_color: str = "#4f46e5"
    # คั่นด้วย | เพื่อให้แก้ใน .env ได้โดยไม่ต้องยุ่งกับ JSON
    widget_suggestions: str = "ลาพักร้อนได้กี่วัน|เบิกค่าเดินทางอย่างไร"

    # ---------- Rate limit ----------
    # คุม "ความถี่" ต่างจากโควตาที่คุม "ปริมาณต่อวัน" — แชทไม่กินโควตาแต่กิน GPU ทุกครั้ง
    rate_limit_chat_per_minute: int = 20
    rate_limit_upload_per_hour: int = 60
    # เชื่อ X-Forwarded-For เฉพาะเมื่ออยู่หลัง Caddy ของเราเอง
    # ถ้าเปิด API ตรงออกอินเทอร์เน็ต ต้องเป็น false ไม่งั้นใครก็ปลอม IP เลี่ยง rate limit ได้
    trust_proxy_headers: bool = True

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.quota_timezone)

    def today(self) -> date:
        """วันที่ตามเวลาไทย — โควตาต้องรีเซ็ตเที่ยงคืนบ้านเรา ไม่ใช่เที่ยงคืน UTC"""
        return datetime.now(self.tz).date()

    def next_quota_reset(self) -> datetime:
        now = datetime.now(self.tz)
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
