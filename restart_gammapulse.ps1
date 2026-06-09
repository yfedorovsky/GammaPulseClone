# restart_gammapulse.ps1 — reliable backend restart (works non-interactively).
#
# Why this exists: start_gammapulse.bat launches via `start "..." cmd /k`, which
# opens interactive console windows that do NOT persist under a non-interactive
# / Task-Scheduler / automation launch, and it TRUNCATES logs\backend.log on every
# start (wiping the day's history). This script:
#   1. stops whatever is listening on :8000,
#   2. (optional) runs the pre-bell gc_aggressive SOP  [-Gc],
#   3. rotates backend.log -> backend.prev.log (keeps one prior session),
#   4. starts uvicorn DETACHED (survives this shell closing),
#   5. polls /api/market-read until the backend answers.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File restart_gammapulse.ps1          # plain restart
#   powershell -ExecutionPolicy Bypass -File restart_gammapulse.ps1 -Gc      # full pre-bell SOP
#   ... -NoVerify    # skip the startup health-check
#
# NOTE: backend only. The Vite frontend is independent and does not need a restart
# to pick up Python/server changes.

param([switch]$Gc, [switch]$NoVerify)

$ErrorActionPreference = 'Continue'
$root = 'C:\Dev\GammaPulse'
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$py = Join-Path $root '.venv\Scripts\python.exe'

Write-Host '[1/5] Stopping backend on :8000 ...'
$conns = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($procId in ($conns.OwningProcess | Select-Object -Unique)) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "    killed PID $procId"
        } catch { Write-Host "    could not kill PID $procId : $_" }
    }
    Start-Sleep -Seconds 3
} else {
    Write-Host '    nothing listening on :8000'
}

if ($Gc) {
    Write-Host '[2/5] gc_aggressive (close stale tracked trades) ...'
    & $py (Join-Path $root 'scripts\gc_aggressive.py')
} else {
    Write-Host '[2/5] skipped gc_aggressive (pass -Gc for full pre-bell SOP)'
}

Write-Host '[3/5] rotating log + launching uvicorn (detached) ...'
$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir 'backend.log'
$err = Join-Path $logDir 'backend.err'
if (Test-Path $log) { Move-Item $log (Join-Path $logDir 'backend.prev.log') -Force }
if (Test-Path $err) { Move-Item $err (Join-Path $logDir 'backend.prev.err') -Force }

$proc = Start-Process -FilePath $py `
    -ArgumentList '-m', 'uvicorn', 'server.main:app', '--host', '0.0.0.0', '--port', '8000' `
    -WorkingDirectory $root `
    -RedirectStandardOutput $log `
    -RedirectStandardError $err `
    -WindowStyle Hidden -PassThru
Write-Host "    uvicorn started, PID $($proc.Id)"

if ($NoVerify) {
    Write-Host '[4/5] verify skipped (-NoVerify)'
    Write-Host '[5/5] done.'
    return
}

Write-Host '[4/5] verifying startup (polling /api/market-read, up to 60s) ...'
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://localhost:8000/api/market-read'
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
}
if ($ok) {
    Write-Host '[5/5] OK — backend UP on http://localhost:8000'
    Write-Host '      tail: Get-Content logs\backend.log -Wait'
    Write-Host '      telegram audit: python scripts\telegram_report.py'
} else {
    Write-Host '[5/5] WARN — no response after 60s. Check logs\backend.err'
    Get-Content $err -Tail 15 -ErrorAction SilentlyContinue
}
