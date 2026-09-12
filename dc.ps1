# ตัวช่วยเรียก docker compose ให้ครบทุกไฟล์ โดยไม่ต้องพิมพ์ -f ยาว ๆ
#
#   .\dc.ps1 up -d
#   .\dc.ps1 logs -f worker
#   .\dc.ps1 exec api alembic upgrade head
#
# ตั้ง $env:RAG_TIER = 'prod' เพื่อใช้ vLLM แทน Ollama (เส้นทางขยาย ดู PLAN.md ข้อ 3)

# ห้ามใช้ 'Stop' — docker compose เขียนความคืบหน้าปกติลง stderr
# แล้ว PowerShell จะตีความเป็น NativeCommandError ทั้งที่คำสั่งสำเร็จ
$ErrorActionPreference = 'Continue'

$files = @('-f', 'docker-compose.yml')

if ($env:RAG_TIER -eq 'prod') {
    $files += @('-f', 'docker-compose.gpu.yml')
} else {
    $files += @('-f', 'docker-compose.local.yml')
}

# override ใช้เฉพาะตอน dev (hot reload) — ตั้ง $env:RAG_ENV = 'prod' เพื่อข้าม
if ($env:RAG_ENV -ne 'prod' -and (Test-Path 'docker-compose.override.yml')) {
    $files += @('-f', 'docker-compose.override.yml')
}

& docker compose @files @args
exit $LASTEXITCODE
