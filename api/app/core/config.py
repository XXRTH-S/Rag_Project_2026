from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

# ตัดพารามิเตอร์ของ libpq ที่ asyncpg ไม่รองรับออกจาก URL
_LIBPQ_ONLY_PARAMS = {"sslmode", "channel_binding", "connect_timeout", "application_name"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        # ชื่อ field อย่าง model_tier / llm_model ชนกับ namespace ที่ pydantic สงวนไว้
        protected_namespaces=(),
    )

    # tier
    model_tier: str = "local"

    # LLM
    llm_base_url: str = "http://ollama:11434/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen3.5:4b"
    llm_max_model_len: int = 8192
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024
    llm_timeout_seconds: int = 180
    llm_enable_thinking: bool = False
    # ตั้งค่าว่างหาก provider ไม่รองรับ reasoning_effort; Ollama ใช้ "none" เพื่อปิด thinking
    llm_reasoning_effort: str = "none"

    # LLM สำรอง
    # เรียก LLM หลัก แล้วลองตัวสำรอง; เว้น base_url ว่างเพื่อปิดตัวสำรอง
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    # หยุดเรียกตัวหลักชั่วคราวหลังล้มติดกันกี่ครั้ง — กันไม่ให้ทุกคำถามต้องรอ timeout
    llm_breaker_threshold: int = 3
    llm_breaker_cooldown_seconds: int = 120
    # แสดงข้อความจากเอกสารแทนเมื่อ LLM ใช้งานไม่ได้; ตั้ง false เพื่อคืนข้อผิดพลาด
    llm_fallback_to_excerpts: bool = True
    # โหลดโมเดลล่วงหน้าเพื่อลดเวลารอคำถามแรก; ปิดได้เพื่อคืน VRAM ให้บริการอื่น
    llm_warmup_on_start: bool = True

    # OCR
    typhoon_ocr_base_url: str = "http://ollama:11434/v1"
    typhoon_ocr_api_key: str = ""
    typhoon_ocr_model: str = "typhoon-ocr"
    typhoon_ocr_task_type: str = "default"
    typhoon_ocr_concurrency: int = 1
    typhoon_ocr_page_timeout: int = 120
    # ส่งหน้าเข้า OCR เมื่อข้อความที่อ่านได้มีน้อยกว่าเกณฑ์นี้
    ocr_min_chars_per_page: int = 50
    # เวลาประมาณต่อหน้าสำหรับคำนวณ ETA; ปรับตามสถิติ ingestion ของเครื่องที่ใช้
    ocr_seconds_per_page: float = 10.0
    # อนุญาตให้ประมวลผลงานค้างใหม่หลังเวลานี้; ควรตั้งให้มากกว่าเวลารอคิวปกติ
    ingestion_stale_after_minutes: int = 30

    # Embedding
    embedding_base_url: str = "http://embeddings:8080"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_device: str = "cpu"
    embedding_api_key: str = ""

    # Datastores
    database_url: str = "postgresql+asyncpg://rag:changeme@postgres:5432/rag"
    redis_url: str = "redis://redis:6379/0"
    # ปิด pool บน serverless เพื่อจำกัดจำนวน connection รวมจากหลาย instance
    db_pool_enabled: bool = True

    # Quota
    quota_timezone: str = "Asia/Bangkok"
    user_daily_document_limit: int = 5
    user_daily_page_limit: int = 500
    user_max_pages_per_document: int = 200
    admin_unlimited: bool = True
    chars_per_page_estimate: int = 3000

    # Retrieval
    # จำกัดจำนวน chunk ที่ส่งให้ LLM เพื่อลดขนาด context และเวลาตอบ
    retrieval_top_k: int = 5
    # เกณฑ์ similarity ขั้นต่ำ; ควรประเมินใหม่เมื่อเปลี่ยน embedding หรือชุดเอกสาร
    retrieval_min_score: float = 0.5
    # รวมผลค้นแบบ keyword และ vector ด้วย RRF
    retrieval_hybrid: bool = True
    # ใช้เกณฑ์ similarity ที่ต่ำลงเมื่อคำค้นตรง เพื่อช่วยค้นหัวข้อและเลขข้อ
    retrieval_keyword_floor: float = 0.40
    chunk_size: int = 800
    chunk_overlap: int = 120

    # App
    # เปิด ingestion เฉพาะระบบที่มี worker, poppler, libmagic และพื้นที่เก็บไฟล์ถาวร
    ingestion_enabled: bool = True
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
    # ปิดเอกสาร API บนระบบที่เปิดให้ภายนอก; เปิดเฉพาะตอนพัฒนาผ่าน override
    api_docs_enabled: bool = False

    # บุคลิกของผู้ช่วย
    # คำลงท้ายสุภาพภาษาไทย — "ครับ" หรือ "ค่ะ" แล้วแต่บุคลิกที่องค์กรเลือก
    # ตั้งเป็นค่าว่างถ้าไม่ต้องการคำลงท้าย (เช่น ใช้กับผู้ใช้ต่างชาติเป็นหลัก)
    bot_polite_particle: str = "ครับ"

    # Chat widget
    widget_title: str = "ผู้ช่วยตอบคำถาม"
    # ใช้สรรพนามเดียวกับ system prompt
    widget_greeting: str = "ถามอะไรก็ได้เกี่ยวกับเอกสารในระบบ เราจะตอบพร้อมอ้างอิงที่มาให้"
    widget_accent_color: str = "#4f46e5"
    # คั่นด้วย | เพื่อให้แก้ใน .env ได้โดยไม่ต้องยุ่งกับ JSON
    widget_suggestions: str = "ลาพักร้อนได้กี่วัน|เบิกค่าเดินทางอย่างไร"

    # Rate limit
    # คุม "ความถี่" ต่างจากโควตาที่คุม "ปริมาณต่อวัน" — แชทไม่กินโควตาแต่กิน GPU ทุกครั้ง
    rate_limit_chat_per_minute: int = 20
    rate_limit_upload_per_hour: int = 60
    # กันการเดารหัสผ่าน · 10 ครั้งต่อ 5 นาที = ราว 2,900 ครั้งต่อวันจาก IP เดียว
    # ซึ่งน้อยเกินกว่าจะไล่เดารหัสที่ยาวพอได้ แต่เผื่อให้คนพิมพ์ผิดหลายรอบได้สบาย ๆ
    #
    # ชั้นหลักนับต่อ IP ไม่ใช่ต่ออีเมล — ถ้านับต่ออีเมลอย่างเดียว ใครก็ยิงรหัสผิด
    # ใส่อีเมลของคนอื่นจนบัญชีเขาเข้าไม่ได้ กลายเป็นเปิดช่องกลั่นแกล้งแทนที่จะปิดช่องโจมตี
    rate_limit_login_attempts: int = 10
    rate_limit_login_window_seconds: int = 300
    # ชั้นรอง นับต่ออีเมล เป็นตาข่ายรับคนที่หมุน IP หนีชั้นแรก
    #
    # ตั้งให้ "หลวมกว่า" ชั้น IP โดยตั้งใจ · เหตุผลที่เคยเลี่ยงการนับต่ออีเมลยังจริงอยู่
    # แต่มันเป็นเหตุผลที่จะไม่ใช้อีเมลเป็นชั้น *เดียว* ไม่ใช่เหตุผลที่จะไม่มีเลย
    # ที่ 30 ครั้งต่อ 15 นาที คนที่จะกลั่นแกล้งต้องยิง 30 ครั้งเพื่อปิดบัญชีคนอื่น
    # แค่ 15 นาที ซึ่งแพงเกินกว่าจะคุ้ม ส่วนคนเดารหัสจริงยังโดนชั้น IP จับก่อนอยู่ดี
    #
    # ตั้ง 0 เพื่อปิดชั้นนี้
    rate_limit_login_attempts_per_email: int = 30
    rate_limit_login_email_window_seconds: int = 900
    # จำกัด Playground แยกด้วย เพราะใช้ทรัพยากร LLM ร่วมกับแชท
    rate_limit_playground_per_minute: int = 10

    # จำนวน proxy ที่เชื่อถือได้: 0 = ต่อตรง, 1 = Caddy, 2 = ngrok + Caddy
    # นับ X-Forwarded-For จากขวา; ห้ามตั้งเกินจำนวน proxy จริง เพราะอาจเชื่อ IP ที่ผู้เรียกปลอมมา
    trusted_proxy_hops: int = 1

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """DATABASE_URL ที่ SQLAlchemy ใช้ได้จริง

        ผู้ให้บริการ Postgres แบบ managed (Neon, Supabase, Railway) คืน URL
        ที่ขึ้นต้นด้วย `postgresql://` หรือ `postgres://` ซึ่ง SQLAlchemy แปลว่า
        "ใช้ psycopg2" — แต่เราไม่ได้ติดตั้ง psycopg2 เพราะโปรเจกต์นี้ใช้ asyncpg
        ผลคือ `create_async_engine` ล้มตั้งแต่ตอน import ด้วย ModuleNotFoundError
        ซึ่งบน serverless โผล่มาเป็นแค่ FUNCTION_INVOCATION_FAILED ตามหาต้นเหตุไม่ได้

        เติม +asyncpg ให้เองแทนที่จะให้คนจำ เพราะการวาง URL ที่เขาให้มาตรง ๆ
        คือสิ่งที่ทุกคนทำ และความผิดพลาดนี้ไม่มีสัญญาณอะไรบอกเลย

        ตัด query param ที่เป็นของ libpq ออกด้วย — asyncpg ไม่รู้จัก `sslmode`
        กับ `channel_binding` แล้วจะโยน TypeError · ค่า sslmode ถูกแปลงไปเป็น
        connect_args แทน (ดู database_connect_args)
        """
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(self.database_url)
        scheme = parts.scheme
        if scheme in ("postgres", "postgresql"):
            scheme = "postgresql+asyncpg"

        keep = [(k, v) for k, v in parse_qsl(parts.query) if k not in _LIBPQ_ONLY_PARAMS]
        return urlunsplit(parts._replace(scheme=scheme, query=urlencode(keep)))

    @property
    def database_connect_args(self) -> dict:
        """ค่าที่ต้องส่งให้ asyncpg โดยตรง ไม่ใช่ผ่าน URL"""
        from urllib.parse import parse_qsl, urlsplit

        query = dict(parse_qsl(urlsplit(self.database_url).query))
        sslmode = query.get("sslmode")
        # asyncpg รับ sslmode เป็นอาร์กิวเมนต์ชื่อ ssl ไม่ใช่ query param
        # 'disable' คือค่าเริ่มต้นอยู่แล้ว ไม่ต้องส่ง
        if sslmode and sslmode != "disable":
            return {"ssl": sslmode}
        return {}

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
