#!/usr/bin/env sh
# ดาวน์โหลดลงไฟล์ชั่วคราวและตรวจ HTTP status ก่อน append เพื่อไม่เขียนทับข้อมูลเดิม
# ใช้ HTTP/1.1 เพื่อลดปัญหา HTTP/2 และพักไฟล์นอก volume ของ Ollama
# ใช้: sh fetch-ollama-blob.sh <url> <sha256> <expected_bytes>

set -eu

URL="$1"
DIGEST="$2"
EXPECTED="$3"

DEST="/downloads/$DIGEST"
PART="/downloads/$DIGEST.part"
MAX_ATTEMPTS=${MAX_ATTEMPTS:-2000}

mkdir -p /downloads

if [ -f "$DEST.done" ]; then
  echo "[skip] โหลดครบแล้ว: $DIGEST"
  exit 0
fi

# กันสองโปรเซสโหลดไฟล์เดียวกันพร้อมกัน — เคยเกิดแล้วและทำให้ไฟล์ 90MB เหลือ 12MB
LOCK="$DEST.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[FAIL] มีโปรเซสอื่นกำลังโหลด blob นี้อยู่ ($LOCK)"
  exit 1
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT INT TERM

[ -f "$DEST" ] || : > "$DEST"

size_of() { stat -c %s "$1" 2>/dev/null || echo 0; }

start=$(size_of "$DEST")
echo "[fetch] $DIGEST — เริ่มที่ $(( start / 1048576 ))/$(( EXPECTED / 1048576 )) MB"

attempt=0
last_report=$start
last_report_at=$(date +%s)

while [ "$(size_of "$DEST")" -lt "$EXPECTED" ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
    echo "[FAIL] ครบ $MAX_ATTEMPTS รอบแล้วยังไม่จบ"
    exit 1
  fi

  offset=$(size_of "$DEST")
  rm -f "$PART"

  code=$(curl -sS -L --http1.1 --connect-timeout 30 --max-time 900 \
              -r "${offset}-" -o "$PART" -w '%{http_code}' "$URL" 2>/dev/null || true)

  got=$(size_of "$PART")
  if [ "$code" = "206" ] && [ "$got" -gt 0 ]; then
    cat "$PART" >> "$DEST"
  elif [ "$code" = "200" ] && [ "$offset" -eq 0 ] && [ "$got" -gt 0 ]; then
    cat "$PART" >> "$DEST"
  fi
  rm -f "$PART"

  now_size=$(size_of "$DEST")
  elapsed=$(( $(date +%s) - last_report_at ))
  if [ "$now_size" -gt "$last_report" ] && [ "$elapsed" -ge 60 ]; then
    rate=$(( (now_size - last_report) / 1024 / elapsed ))
    remain_min=0
    [ "$rate" -gt 0 ] && remain_min=$(( (EXPECTED - now_size) / 1024 / rate / 60 ))
    echo "[$(date '+%H:%M:%S')] $(( now_size / 1048576 ))/$(( EXPECTED / 1048576 )) MB · ${rate} KB/s · เหลือ ~${remain_min} นาที · รอบที่ $attempt"
    last_report=$now_size
    last_report_at=$(date +%s)
  fi

  [ "$(size_of "$DEST")" -lt "$EXPECTED" ] && sleep 2
done

echo "[verify] $DIGEST"
ACTUAL=$(sha256sum "$DEST" | cut -d' ' -f1)
if [ "$ACTUAL" != "$DIGEST" ]; then
  echo "[FAIL] sha256 ไม่ตรง — ลบแล้วต้องเริ่มใหม่"
  echo "  ต้องการ: $DIGEST"
  echo "  ได้:     $ACTUAL"
  rm -f "$DEST"
  exit 1
fi

touch "$DEST.done"
echo "[ok] $DIGEST พร้อมแล้ว"
