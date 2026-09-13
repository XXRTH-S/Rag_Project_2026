# รันตรวจทุกอย่างเหมือนที่ CI ทำ ก่อน commit
#
#   .\test.ps1         ตรวจทั้งหมด
#   .\test.ps1 -Quick  ข้ามเทสฝั่ง API ที่ใช้เวลาราวสองนาที
#
# ต้องเปิด docker ไว้ก่อน เพราะทุกอย่างรันในคอนเทนเนอร์ตามที่โปรเจกต์นี้ออกแบบไว้

param([switch]$Quick)

$failed = @()

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)

    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ล้มเหลว" -ForegroundColor Red
        $script:failed += $Name
    } else {
        Write-Host "  ผ่าน" -ForegroundColor Green
    }
}

Invoke-Step "api · lint" { & .\dc.ps1 exec -T api ruff check app tests }
Invoke-Step "web · lint + typecheck + test" { & .\dc.ps1 exec -T web npm run check }

if (-not $Quick) {
    # ล้างตัวนับ rate limit ก่อน ไม่งั้นเทสที่รันต่อจากการใช้งานจริงจะชนเพดาน
    # แล้วล้มด้วย 429 ทั้งที่ไม่เกี่ยวกับสิ่งที่กำลังทดสอบ
    & .\dc.ps1 exec -T redis redis-cli --scan --pattern 'rl:*' | ForEach-Object {
        & .\dc.ps1 exec -T redis redis-cli del $_ | Out-Null
    }
    Invoke-Step "api · pytest" { & .\dc.ps1 exec -T api python -m pytest -q }
}

Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "ผ่านทั้งหมด" -ForegroundColor Green
    exit 0
}

Write-Host "ล้มเหลว $($failed.Count) รายการ:" -ForegroundColor Red
$failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
exit 1
