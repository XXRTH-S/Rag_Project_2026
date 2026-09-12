#!/usr/bin/env sh
# ย้ายไฟล์ที่โหลดครบแล้วจาก /downloads เข้า blobs ของ ollama
#
# แยกจากขั้นโหลดโดยตั้งใจ: ทำตอนท้ายสุดแล้วสั่ง `ollama pull` ต่อทันที
# เพื่อให้ manifest ถูกเขียนก่อนที่ ollama จะมีโอกาส restart แล้วกวาด blob ทิ้ง
#
# ใช้: sh stage-ollama-blobs.sh <sha256> [<sha256> ...]

set -eu

BLOBS=/root/.ollama/models/blobs
mkdir -p "$BLOBS"

for DIGEST in "$@"; do
  SRC="/downloads/$DIGEST"
  DST="$BLOBS/sha256-$DIGEST"

  if [ -f "$DST" ]; then
    echo "[skip] blob อยู่แล้ว: sha256-$DIGEST"
    continue
  fi
  if [ ! -f "$SRC.done" ]; then
    echo "[FAIL] ยังโหลดไม่ครบ: $DIGEST"
    exit 1
  fi

  cp "$SRC" "$DST"
  # ลบร่องรอยการโหลดของ ollama เอง ไม่งั้นมันจะพยายามโหลดต่อจากของเดิม
  rm -f "$BLOBS/sha256-$DIGEST-partial" "$BLOBS/sha256-$DIGEST-partial-"*
  echo "[ok] วาง blob: sha256-$DIGEST"
done
