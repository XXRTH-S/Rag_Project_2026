# สำรองข้อมูลของระบบ
#
#   .\backup.ps1                    สำรองลง .\backups
#   .\backup.ps1 -Path D:\backups   ระบุที่เก็บเอง
#   .\backup.ps1 -KeepDays 14       เก็บย้อนหลังกี่วัน (ค่าเริ่มต้น 30)
#
# สิ่งที่สำรอง:
#   1. ฐานข้อมูล (pg_dump) — เอกสาร, chunk + embedding, โควตา, ประวัติแชท, feedback
#   2. ไฟล์ต้นฉบับที่ผู้ใช้อัปโหลด
#
# สิ่งที่ *ไม่* สำรองโดยตั้งใจ:
#   - โมเดลใน Ollama และ cache ของ TEI — ดาวน์โหลดใหม่ได้ และรวมกันหลายกิกะไบต์
#     ถ้าเน็ตช้าและอยากเก็บไว้ ให้สำรอง volume rag-workshop_ollama-models แยกต่างหาก

param(
    [string]$Path = "backups",
    [int]$KeepDays = 30
)

$ErrorActionPreference = 'Continue'

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dir = Join-Path $Path $stamp
New-Item -ItemType Directory -Force -Path $dir | Out-Null
# docker -v ต้องใช้ path เต็ม — path แบบ relative จะล้มด้วย exit 125
$dirFull = (Resolve-Path $dir).Path

$compose = 'docker compose -f docker-compose.yml -f docker-compose.local.yml'

Write-Host "สำรองข้อมูลไปที่ $dir" -ForegroundColor Cyan

# ---------- ฐานข้อมูล ----------
Write-Host "  [1/2] ฐานข้อมูล..." -NoNewline
$dumpFile = Join-Path $dir 'postgres.dump'

# ห้าม pipe ผลลัพธ์ binary ผ่าน PowerShell — มันส่งเป็นสตริงแล้วไฟล์ dump จะพัง
# เขียนไฟล์ในคอนเทนเนอร์ก่อนแล้วค่อย copy ออกมา
# -Fc = custom format บีบอัดในตัวและ restore ทีละตารางได้
& docker compose -f docker-compose.yml -f docker-compose.local.yml `
    exec -T postgres sh -c "pg_dump -U rag -d rag -Fc -f /tmp/rag-backup.dump" 2>&1 | Out-Null
& docker compose -f docker-compose.yml -f docker-compose.local.yml `
    cp postgres:/tmp/rag-backup.dump $dumpFile 2>&1 | Out-Null
& docker compose -f docker-compose.yml -f docker-compose.local.yml `
    exec -T postgres rm -f /tmp/rag-backup.dump 2>&1 | Out-Null

if ((Test-Path $dumpFile) -and (Get-Item $dumpFile).Length -gt 1024) {
    Write-Host " OK ($([math]::Round((Get-Item $dumpFile).Length / 1MB, 1)) MB)" -ForegroundColor Green
} else {
    Write-Host " ล้มเหลว" -ForegroundColor Red
    exit 1
}

# ---------- ไฟล์ที่อัปโหลด ----------
Write-Host "  [2/2] ไฟล์ที่อัปโหลด..." -NoNewline
$uploadsFile = Join-Path $dir 'uploads.tar.gz'
# ใช้ image ของโปรเจกต์เอง ไม่ดึง alpine เพิ่ม — บนเน็ตช้าการ pull image ใหม่ทำให้ backup ล้ม
& docker run --rm --user root -v rag-workshop_uploads:/data -v "${dirFull}:/backup" `
    rag-workshop-api:latest tar czf /backup/uploads.tar.gz -C /data . 2>&1 | Out-Null

if (Test-Path $uploadsFile) {
    Write-Host " OK ($([math]::Round((Get-Item $uploadsFile).Length / 1MB, 1)) MB)" -ForegroundColor Green
} else {
    Write-Host " ข้าม (ยังไม่มีไฟล์)" -ForegroundColor Yellow
}

# ---------- ลบของเก่า ----------
$cutoff = (Get-Date).AddDays(-$KeepDays)
$removed = 0
Get-ChildItem -Path $Path -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.CreationTime -lt $cutoff } |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force; $removed++ }

Write-Host "เสร็จ — เก็บย้อนหลัง $KeepDays วัน (ลบชุดเก่า $removed ชุด)" -ForegroundColor Cyan
Write-Host ""
Write-Host "วิธีกู้คืน:" -ForegroundColor Yellow
Write-Host "  docker compose -f docker-compose.yml cp `"$dumpFile`" postgres:/tmp/restore.dump"
Write-Host "  .\dc.ps1 exec -T postgres pg_restore -U rag -d rag --clean --if-exists /tmp/restore.dump"
Write-Host "  docker run --rm --user root -v rag-workshop_uploads:/data -v `"${dirFull}:/backup`" rag-workshop-api:latest tar xzf /backup/uploads.tar.gz -C /data"
