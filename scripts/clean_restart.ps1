<#
.SYNOPSIS
    Clean restart of GammaPulse backend + Theta Terminal in the right order.

.DESCRIPTION
    Pattern recognition (May 8 2026): when the very first subscription request
    to ThetaData returns MAX_STREAMS_REACHED (id=0), Theta Terminal still
    holds phantom subscriptions from previous backend sessions in this
    process tree. Restarting the backend alone doesn't fix it because the
    server-side subscription registry persists. Restart sequence MUST be:

        1. Stop backend (release the websocket cleanly)
        2. Stop Theta Terminal (clears server-side subscription registry)
        3. Wait for ports to release
        4. Relaunch Theta Terminal
        5. Wait for Theta REST to respond
        6. Relaunch backend

    This script automates 1-5 and leaves backend launch to the operator
    (because uvicorn typically wants its own foreground terminal).

.PARAMETER ThetaJar
    Path to ThetaTerminalv3.jar. Default: C:\Users\yfedo\Downloads\ThetaTerminalv3.jar

.PARAMETER ThetaCreds
    Path to a text file containing two lines: email and password for Theta
    Terminal headless login. If absent, Theta launches interactively (you
    finish the login). Default: $env:USERPROFILE\.thetadata-creds.txt

.PARAMETER BackendPort
    Port the backend listens on (used to detect a running uvicorn). Default: 8000

.PARAMETER ThetaRestPort
    Theta Terminal's REST endpoint port for health-check polling. Default: 25503

.PARAMETER SkipTheta
    If $true, only bounce the backend (skip Theta restart). Use when you know
    Theta is healthy and only the backend code changed. Default: $false

.PARAMETER WaitForBackendStop
    Seconds to wait for graceful backend shutdown before force-killing. Default: 8

.PARAMETER WaitForThetaReady
    Max seconds to wait for Theta REST to come back online. Default: 60

.EXAMPLE
    # Full clean restart (default — bounces both)
    .\scripts\clean_restart.ps1

.EXAMPLE
    # Backend only (Theta is healthy, just code changed)
    .\scripts\clean_restart.ps1 -SkipTheta

.EXAMPLE
    # Override the Theta jar location
    .\scripts\clean_restart.ps1 -ThetaJar "D:\tools\ThetaTerminal.jar"

.NOTES
    After this script finishes successfully, START THE BACKEND in your
    uvicorn terminal:
        uvicorn server.main:app --host 0.0.0.0 --port 8000

    Watch for "[SWEEP] subscription plan: ..." log line. If you see
    MAX_STREAMS_REACHED at id=0, this script either didn't kill Theta
    cleanly or the cap is genuinely exceeded — re-run with -SkipTheta:$false.
#>

[CmdletBinding()]
param(
    [string]$ThetaJar = "$env:USERPROFILE\Downloads\ThetaTerminalv3.jar",
    [string]$ThetaCreds = "$env:USERPROFILE\.thetadata-creds.txt",
    [int]$BackendPort = 8000,
    [int]$ThetaRestPort = 25503,
    [switch]$SkipTheta = $false,
    [int]$WaitForBackendStop = 8,
    [int]$WaitForThetaReady = 60
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host "[restart] $msg" -ForegroundColor Cyan
}

function Write-Good([string]$msg) {
    Write-Host "[restart] $msg" -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "[restart] $msg" -ForegroundColor Yellow
}

function Write-Bad([string]$msg) {
    Write-Host "[restart] $msg" -ForegroundColor Red
}

# ── Step 1: Stop the backend ──────────────────────────────────────────

Write-Step "Step 1/5: stopping backend on port $BackendPort..."
$backendConn = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue
if ($backendConn) {
    $backendPid = $backendConn.OwningProcess
    $backendProc = Get-Process -Id $backendPid -ErrorAction SilentlyContinue
    if ($backendProc) {
        Write-Step "  found backend PID=$backendPid ($($backendProc.ProcessName)), started $($backendProc.StartTime)"
        # Try graceful shutdown via Ctrl+C-equivalent (CloseMainWindow). Falls back
        # to force-kill if it doesn't exit within WaitForBackendStop seconds.
        $closed = $backendProc.CloseMainWindow()
        if (-not $closed) {
            Write-Warn "  CloseMainWindow refused; using Stop-Process"
        }
        $deadline = (Get-Date).AddSeconds($WaitForBackendStop)
        while ((Get-Date) -lt $deadline) {
            if (-not (Get-Process -Id $backendPid -ErrorAction SilentlyContinue)) {
                break
            }
            Start-Sleep -Milliseconds 500
        }
        if (Get-Process -Id $backendPid -ErrorAction SilentlyContinue) {
            Write-Warn "  backend didn't exit in ${WaitForBackendStop}s — force-killing"
            Stop-Process -Id $backendPid -Force
            Start-Sleep -Seconds 1
        }
        Write-Good "  backend stopped"
    }
} else {
    Write-Step "  no backend listening on $BackendPort (already stopped)"
}

if ($SkipTheta) {
    Write-Good "Skipping Theta restart (SkipTheta=true). You can now restart backend."
    return
}

# ── Step 2: Stop Theta Terminal ───────────────────────────────────────

Write-Step "Step 2/5: stopping Theta Terminal..."

# Find Java processes whose command line references the Theta jar — narrow
# match so we don't accidentally kill IntelliJ, Eclipse, Minecraft, etc.
$jarBasename = [System.IO.Path]::GetFileNameWithoutExtension($ThetaJar)
$thetaProcesses = Get-WmiObject Win32_Process -Filter "Name='java.exe' OR Name='javaw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match [regex]::Escape($jarBasename) -or $_.CommandLine -match "Theta" }

if (-not $thetaProcesses) {
    Write-Step "  no Theta Terminal processes found (already stopped)"
} else {
    foreach ($p in $thetaProcesses) {
        Write-Step "  killing Theta PID=$($p.ProcessId)"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Write-Good "  Theta Terminal stopped"
}

# ── Step 3: Wait for ports to release ─────────────────────────────────

Write-Step "Step 3/5: waiting for ports to release..."
$portsToCheck = @($BackendPort, $ThetaRestPort, 25520)  # backend, theta REST, theta WS
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    $stillBound = $portsToCheck | Where-Object {
        Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue
    }
    if (-not $stillBound) { break }
    Start-Sleep -Milliseconds 500
}
$stillBound = $portsToCheck | Where-Object {
    Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue
}
if ($stillBound) {
    Write-Warn "  ports still bound: $($stillBound -join ',') — orphan process? continuing anyway"
} else {
    Write-Good "  all ports released"
}

# ── Step 4: Relaunch Theta Terminal ──────────────────────────────────

Write-Step "Step 4/5: relaunching Theta Terminal..."
if (-not (Test-Path $ThetaJar)) {
    Write-Bad "  ThetaJar not found at: $ThetaJar"
    Write-Bad "  Pass -ThetaJar <path> or copy the jar to that location."
    exit 1
}

$javaArgs = @("-jar", $ThetaJar)
# Optional headless login — pass username/password if creds file exists.
# Format: line 1 = email, line 2 = password.
if (Test-Path $ThetaCreds) {
    $lines = Get-Content $ThetaCreds -ErrorAction SilentlyContinue
    if ($lines.Count -ge 2) {
        $javaArgs += @($lines[0], $lines[1])
        Write-Step "  using headless creds from $ThetaCreds"
    }
}

# Launch detached so the script can continue. Output suppressed to avoid
# cluttering the operator's terminal.
$thetaProc = Start-Process -FilePath "javaw.exe" -ArgumentList $javaArgs `
    -WindowStyle Hidden -PassThru -ErrorAction Continue
if (-not $thetaProc) {
    # javaw not on PATH? try java
    $thetaProc = Start-Process -FilePath "java.exe" -ArgumentList $javaArgs `
        -WindowStyle Hidden -PassThru -ErrorAction Continue
}
if (-not $thetaProc) {
    Write-Bad "  failed to launch Theta Terminal — is Java installed and on PATH?"
    exit 1
}
Write-Step "  Theta Terminal launched (PID=$($thetaProc.Id))"

# ── Step 5: Wait for Theta REST to respond ────────────────────────────

Write-Step "Step 5/5: waiting up to ${WaitForThetaReady}s for Theta REST on :$ThetaRestPort..."
$deadline = (Get-Date).AddSeconds($WaitForThetaReady)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        # Any 2xx-or-4xx HTTP response means the listener is up. Theta returns
        # an upgrade notice on the legacy snapshot path — fine, we just want
        # confirmation the process is serving HTTP.
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$ThetaRestPort/snapshot/stock/quote?symbol=SPY" `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $ready = $true
        break
    } catch {
        # 4xx counts as "alive but rejecting" — also good
        if ($_.Exception.Response.StatusCode.value__ -ge 400) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    Write-Bad "  Theta REST didn't come online in ${WaitForThetaReady}s"
    Write-Bad "  Open Theta Terminal manually, complete login, then restart backend."
    exit 1
}
Write-Good "  Theta REST is responding"

# ── Done ──────────────────────────────────────────────────────────────

Write-Host ""
Write-Good "==============================================================="
Write-Good "  Theta Terminal is up. Now start the backend:"
Write-Good ""
Write-Good "    cd C:\Dev\GammaPulse"
Write-Good "    uvicorn server.main:app --host 0.0.0.0 --port 8000"
Write-Good ""
Write-Good "  Watch for [SWEEP] subscription plan and confirm NO"
Write-Good "  MAX_STREAMS_REACHED messages in the first 30 seconds."
Write-Good "==============================================================="
