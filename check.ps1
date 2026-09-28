# ดูสถานะระบบและความคืบหน้าการโหลดโมเดลในคำสั่งเดียว
#
#   .\check.ps1          ดูครั้งเดียว
#   .\check.ps1 -Watch   ดูแบบรีเฟรชทุก 20 วินาที (Ctrl+C เพื่อออก)

param([switch]$Watch, [int]$Every = 20)

$ErrorActionPreference = 'Continue'

function Show-Status {
    Write-Host "`n=== $(Get-Date -Format 'HH:mm:ss') ===" -ForegroundColor Cyan

    Write-Host "`n[ คอนเทนเนอร์ ]" -ForegroundColor Yellow
    & .\dc.ps1 ps --format "table {{.Service}}`t{{.Status}}"

    Write-Host "`n[ ความคืบหน้าโหลดโมเดล ]" -ForegroundColor Yellow
    # tmp-* คือไฟล์ที่กำลังโหลด ส่วน sha256-* โหลดเสร็จแล้ว
    # หลีกเลี่ยง double quote ในคำสั่งนี้ เพราะ PowerShell 5.1 ส่งต่อให้ native command ไม่ครบ
    $listBlobs = 'for f in /m/models/blobs/tmp-* /m/models/blobs/sha256-*; do case $f in *partial*) continue;; esac; [ -f $f ] || continue; echo $(( $(stat -c %s $f) / 1048576 )) MB $(basename $f | cut -c1-20); done'
    $blobs = docker run --rm --user root -v rag-workshop_ollama-models:/m rag-workshop-api:latest sh -c $listBlobs 2>$null
    if ($blobs) { $blobs | ForEach-Object { Write-Host "  $_" } }
    else { Write-Host "  (ยังไม่มี blob)" }

    # ใช้ --since ไม่ใช่ --tail เพราะ restart ไม่ล้าง log เดิม แล้วจะเห็น stall เก่าค้างอยู่
    $stalls = (& .\dc.ps1 logs --since 3m ollama 2>&1 | Select-String 'stalled').Count
    if ($stalls -gt 0) { Write-Host "  ollama stall (3 นาทีล่าสุด): $stalls ครั้ง" -ForegroundColor DarkYellow }

    Write-Host "`n[ โมเดลที่พร้อมใช้ ]" -ForegroundColor Yellow
    & .\dc.ps1 exec -T ollama ollama list 2>$null

    Write-Host "`n[ โมเดลที่โหลดอยู่ใน VRAM ]" -ForegroundColor Yellow
    # PROCESSOR ต้องเป็น 100% GPU — ถ้ามี CPU ปนแปลว่าล้น VRAM แล้วจะช้าลง 5-10 เท่า
    & .\dc.ps1 exec -T ollama ollama ps 2>$null

    Write-Host "`n[ VRAM ]" -ForegroundColor Yellow
    # ต้องใส่ quote — ถ้าไม่ใส่ PowerShell จะตีความ comma เป็น array literal
    # แล้ว nvidia-smi จะได้ argument ที่ถูกหั่นเป็นชิ้น ๆ
    & .\dc.ps1 exec -T ollama nvidia-smi "--query-gpu=memory.used,memory.free" "--format=csv,noheader" 2>$null

    Write-Host "`n[ health ]" -ForegroundColor Yellow
    # ใช้ curl.exe เพราะ /health/deep ตอบ 503 ตอน degraded ซึ่งถูกต้องตามสเปก
    # แต่ Invoke-RestMethod ของ PS 5.1 จะโยน exception แล้วอ่าน body ไม่ได้
    $raw = curl.exe -s --max-time 60 http://localhost:8000/health/deep 2>$null
    if (-not $raw) {
        Write-Host "  ต่อ API ไม่ได้" -ForegroundColor Red
    } else {
        $h = $raw | ConvertFrom-Json
        foreach ($k in $h.checks.PSObject.Properties.Name) {
            $c = $h.checks.$k
            $mark = if ($c.ok) { 'OK  ' } else { 'FAIL' }
            $color = if ($c.ok) { 'Green' } else { 'Red' }
            Write-Host ("  {0} {1,-12} {2}" -f $mark, $k, $c.detail) -ForegroundColor $color
        }
        # /health/deep แจกรายละเอียด (รุ่น ชื่อโมเดล สถานะ GPU) เฉพาะ admin
        # สคริปต์นี้ยิงโดยไม่ล็อกอิน จึงได้แค่เขียว/แดง ซึ่งพอสำหรับการเช็คว่าระบบขึ้นครบ
        if ($h.gpu) {
            Write-Host "  gpu: $($h.gpu.loaded_models)"
            if ($h.gpu.warning) { Write-Host "  $($h.gpu.warning)" -ForegroundColor Red }
        } else {
            Write-Host "  (รายละเอียดและสถานะ GPU ดูที่หน้า /status ด้วยบัญชี admin)" -ForegroundColor DarkGray
        }
    }
}

if ($Watch) {
    while ($true) { Show-Status; Start-Sleep -Seconds $Every }
} else {
    Show-Status
}
