"""initial schema: users, quota, documents, chunks, chat

Revision ID: 0001
Revises:
Create Date: 2026-09-05

เขียนเป็น raw SQL เพราะ pgvector + HNSW index + partial index
เขียนตรง ๆ อ่านง่ายกว่าและตรงกับสิ่งที่ Postgres ได้รับจริง
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    # pg_trgm ใช้ทำ fuzzy match ชื่อเอกสารในหน้า admin
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        """
        CREATE TABLE users (
            id            UUID PRIMARY KEY,
            email         VARCHAR(320) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            role          VARCHAR(16)  NOT NULL DEFAULT 'user',
            is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT ck_users_role CHECK (role IN ('user', 'admin'))
        )
        """
    )
    op.execute("CREATE INDEX ix_users_email ON users (email)")

    op.execute(
        """
        CREATE TABLE documents (
            id                   UUID PRIMARY KEY,
            owner_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename             VARCHAR(512)  NOT NULL,
            mime_type            VARCHAR(128)  NOT NULL,
            storage_path         VARCHAR(1024) NOT NULL,
            size_bytes           INTEGER       NOT NULL DEFAULT 0,
            status               VARCHAR(16)   NOT NULL DEFAULT 'pending',
            collection           VARCHAR(64)   NOT NULL DEFAULT 'default',
            page_count           INTEGER       NOT NULL DEFAULT 0,
            page_count_estimated BOOLEAN       NOT NULL DEFAULT FALSE,
            ocr_page_count       INTEGER       NOT NULL DEFAULT 0,
            created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT ck_documents_status
                CHECK (status IN ('pending', 'processing', 'ready', 'failed'))
        )
        """
    )
    op.execute("CREATE INDEX ix_documents_owner ON documents (owner_id)")
    op.execute("CREATE INDEX ix_documents_status ON documents (status)")
    op.execute("CREATE INDEX ix_documents_collection ON documents (collection)")
    op.execute("CREATE INDEX ix_documents_filename_trgm ON documents USING gin (filename gin_trgm_ops)")

    # หนึ่งแถวต่อ (user, วันตามเวลาไทย) — unique constraint คือหัวใจของการกัน race
    # ตอน user อัปหลายไฟล์พร้อมกัน
    op.execute(
        """
        CREATE TABLE usage_counters (
            id              UUID PRIMARY KEY,
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            usage_date      DATE NOT NULL,
            documents_used  INTEGER NOT NULL DEFAULT 0,
            pages_used      INTEGER NOT NULL DEFAULT 0,
            pages_reserved  INTEGER NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_usage_user_date UNIQUE (user_id, usage_date),
            CONSTRAINT ck_usage_non_negative
                CHECK (documents_used >= 0 AND pages_used >= 0 AND pages_reserved >= 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE quota_events (
            id              UUID PRIMARY KEY,
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            document_id     UUID REFERENCES documents(id) ON DELETE SET NULL,
            action          VARCHAR(16) NOT NULL,
            delta_documents INTEGER NOT NULL DEFAULT 0,
            delta_pages     INTEGER NOT NULL DEFAULT 0,
            note            VARCHAR(255),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_quota_events_action
                CHECK (action IN ('reserve', 'commit', 'release'))
        )
        """
    )
    op.execute("CREATE INDEX ix_quota_events_user ON quota_events (user_id, created_at DESC)")

    op.execute(
        """
        CREATE TABLE ingestion_jobs (
            id             UUID PRIMARY KEY,
            document_id    UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            stage          VARCHAR(16) NOT NULL DEFAULT 'queued',
            progress       INTEGER NOT NULL DEFAULT 0,
            pages_done     INTEGER NOT NULL DEFAULT 0,
            pages_total    INTEGER NOT NULL DEFAULT 0,
            error          TEXT,
            queue          VARCHAR(32) NOT NULL DEFAULT 'ocr_user',
            celery_task_id VARCHAR(64),
            gpu_seconds    DOUBLE PRECISION NOT NULL DEFAULT 0,
            processor_note VARCHAR(64),
            queued_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at     TIMESTAMPTZ,
            finished_at    TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX ix_jobs_document ON ingestion_jobs (document_id)")
    op.execute("CREATE INDEX ix_jobs_stage ON ingestion_jobs (stage)")
    # หา job ที่ยังค้างอยู่ในคิวได้เร็ว โดยไม่ต้องสแกนทั้งตาราง
    op.execute(
        """
        CREATE INDEX ix_jobs_pending ON ingestion_jobs (queued_at)
        WHERE stage NOT IN ('done', 'failed')
        """
    )

    op.execute(
        f"""
        CREATE TABLE chunks (
            id          UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            owner_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ordinal     INTEGER NOT NULL,
            text        TEXT NOT NULL,
            page_no     INTEGER,
            token_count INTEGER NOT NULL DEFAULT 0,
            source      VARCHAR(16) NOT NULL DEFAULT 'parse',
            embedding   VECTOR({EMBEDDING_DIM}),
            metadata    JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_chunks_source CHECK (source IN ('parse', 'ocr'))
        )
        """
    )
    op.execute("CREATE INDEX ix_chunks_document ON chunks (document_id)")
    op.execute("CREATE INDEX ix_chunks_owner ON chunks (owner_id)")
    op.execute("CREATE INDEX ix_chunks_metadata ON chunks USING gin (metadata)")
    # HNSW เร็วกว่า IVFFlat มากที่ขนาดข้อมูลระดับนี้ และไม่ต้อง train ก่อนใช้
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    op.execute(
        """
        CREATE TABLE prompt_configs (
            id              UUID PRIMARY KEY,
            name            VARCHAR(128) NOT NULL,
            system_prompt   TEXT NOT NULL,
            top_k           INTEGER NOT NULL DEFAULT 8,
            temperature     DOUBLE PRECISION NOT NULL DEFAULT 0.2,
            min_score       DOUBLE PRECISION NOT NULL DEFAULT 0.35,
            enable_thinking BOOLEAN NOT NULL DEFAULT FALSE,
            is_active       BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # มี prompt config ที่ active ได้แค่ตัวเดียวเท่านั้น บังคับที่ระดับ DB
    op.execute(
        "CREATE UNIQUE INDEX ux_prompt_configs_active ON prompt_configs (is_active) WHERE is_active"
    )

    op.execute(
        """
        CREATE TABLE chat_sessions (
            id         UUID PRIMARY KEY,
            channel    VARCHAR(16) NOT NULL DEFAULT 'widget',
            user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
            user_agent VARCHAR(512),
            client_ip  VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_sessions_channel CHECK (channel IN ('widget', 'playground'))
        )
        """
    )
    op.execute("CREATE INDEX ix_sessions_created ON chat_sessions (created_at DESC)")
    op.execute("CREATE INDEX ix_sessions_channel ON chat_sessions (channel)")

    op.execute(
        """
        CREATE TABLE chat_messages (
            id                    UUID PRIMARY KEY,
            session_id            UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role                  VARCHAR(16) NOT NULL,
            content               TEXT NOT NULL,
            latency_ms            INTEGER,
            prompt_tokens         INTEGER,
            completion_tokens     INTEGER,
            model                 VARCHAR(128),
            prompt_config_id      UUID REFERENCES prompt_configs(id) ON DELETE SET NULL,
            answered_from_context BOOLEAN NOT NULL DEFAULT TRUE,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_messages_role CHECK (role IN ('user', 'assistant', 'system'))
        )
        """
    )
    op.execute("CREATE INDEX ix_messages_session ON chat_messages (session_id)")
    op.execute("CREATE INDEX ix_messages_created ON chat_messages (created_at DESC)")
    # หา "คำถามที่ระบบตอบไม่ได้" สำหรับหน้า analytics โดยไม่สแกนทั้งตาราง
    op.execute(
        """
        CREATE INDEX ix_messages_unanswered ON chat_messages (created_at DESC)
        WHERE NOT answered_from_context
        """
    )

    op.execute(
        """
        CREATE TABLE message_citations (
            id         UUID PRIMARY KEY,
            message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            chunk_id   UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            score      DOUBLE PRECISION NOT NULL,
            rank       INTEGER NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_citations_message ON message_citations (message_id)")
    op.execute("CREATE INDEX ix_citations_chunk ON message_citations (chunk_id)")

    op.execute(
        """
        CREATE TABLE feedback (
            id         UUID PRIMARY KEY,
            message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            rating     INTEGER NOT NULL,
            comment    TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_feedback_rating CHECK (rating IN (-1, 1))
        )
        """
    )
    op.execute("CREATE INDEX ix_feedback_message ON feedback (message_id)")


def downgrade() -> None:
    for table in (
        "feedback",
        "message_citations",
        "chat_messages",
        "chat_sessions",
        "prompt_configs",
        "chunks",
        "ingestion_jobs",
        "quota_events",
        "usage_counters",
        "documents",
        "users",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
