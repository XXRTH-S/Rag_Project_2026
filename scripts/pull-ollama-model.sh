#!/usr/bin/env bash
# ติดตามขนาด blob และ restart Ollama เมื่อไม่คืบหน้าภายใน STALL_LIMIT
# ต้องตั้ง OLLAMA_NOPRUNE=1 เพื่อเก็บข้อมูลที่โหลดค้างไว้
# ใช้: bash scripts/pull-ollama-model.sh qwen3.5:4b [ชื่อ alias]

set -u

MODEL="${1:?ต้องระบุชื่อโมเดล}"
ALIAS="${2:-}"
STALL_LIMIT="${STALL_LIMIT:-300}"
CHECK_EVERY="${CHECK_EVERY:-60}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-100}"

cd "$(dirname "$0")/.." || exit 1
DC="docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.override.yml"

blob_mb() {
  $DC exec -T ollama du -sm /root/.ollama/models/blobs 2>/dev/null | cut -f1 | tr -d '[:space:]'
}

model_present() {
  $DC exec -T ollama ollama list 2>/dev/null | grep -q "^${MODEL%%:*}"
}

if model_present; then
  echo "[skip] มี $MODEL อยู่แล้ว"
  exit 0
fi

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "[$(date '+%H:%M:%S')] เริ่ม pull $MODEL (รอบ $attempt)"

  $DC exec -T ollama ollama pull "$MODEL" >/dev/null 2>&1 &
  pull_pid=$!

  last=$(blob_mb); last=${last:-0}
  last_change=$(date +%s)

  while kill -0 "$pull_pid" 2>/dev/null; do
    sleep "$CHECK_EVERY"
    current=$(blob_mb); current=${current:-$last}
    now=$(date +%s)

    if [ "$current" -gt "$last" ]; then
      elapsed=$((now - last_change))
      [ "$elapsed" -lt 1 ] && elapsed=1
      echo "[$(date '+%H:%M:%S')] ${current} MB (+$((current - last)) MB · $(((current - last) * 1024 / elapsed)) KB/s)"
      last=$current
      last_change=$now
    elif [ $((now - last_change)) -ge "$STALL_LIMIT" ]; then
      echo "[$(date '+%H:%M:%S')] ค้างมา $((now - last_change)) วินาที — ฆ่าแล้วเริ่มใหม่"
      kill -9 "$pull_pid" 2>/dev/null
      # restart เพื่อตัด pull ฝั่ง server ที่ยังค้าง ไม่งั้นรอบใหม่จะแย่งกันเอง
      $DC restart ollama >/dev/null 2>&1
      sleep 5
      break
    fi
  done

  wait "$pull_pid" 2>/dev/null

  if model_present; then
    [ -n "$ALIAS" ] && $DC exec -T ollama ollama cp "$MODEL" "$ALIAS" >/dev/null 2>&1
    echo "================ RESULT ================"
    echo "MODEL_READY $MODEL"
    $DC exec -T ollama ollama list
    exit 0
  fi

  sleep 10
done

echo "================ RESULT ================"
echo "MODEL_FAILED $MODEL"
exit 1
