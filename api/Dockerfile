FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# poppler-utils : pdftoppm แปลงหน้า PDF เป็นภาพก่อนส่งเข้า OCR (และ pdftotext สำหรับ anchor text)
# libmagic1     : python-magic ตรวจ MIME จริง ไม่เชื่อนามสกุลไฟล์
# curl          : healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        libmagic1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ติดตั้ง deps ก่อน copy โค้ด เพื่อให้ layer cache ทำงาน
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY . .

RUN useradd -m -u 1000 app && mkdir -p /data/uploads && chown -R app:app /app /data
USER app

EXPOSE 8000


# ---- dev: hot reload, โค้ด mount ทับจาก host ----
FROM base AS dev
USER root
RUN pip install pytest pytest-asyncio ruff
USER app


# ---- prod ----
FROM base AS prod
