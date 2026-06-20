<#
  Register the GammaPulse backend watchdog (task #91) as a Windows Scheduled Task.

  WHY a scheduled task and NOT a line in start_gammapulse.bat:
  the failure this guards against is "nobody ran start_gammapulse.bat" (the 6/17
  silent-zero-flow day). A watchdog launched BY that same bat would also be absent
  on exactly the day it's needed. It must run independently of the backend.

  Run this ONCE (from an elevated PowerShell if you want "run whether logged on or
  not"; otherwise it runs as the current user, which is fine for an always-logged-in
  trading box):

      powershell -ExecutionPolicy Bypass -File scripts\register_watchdog_task.ps1

  Default: --once every 2 minutes (most robust — each check is a fresh process, so a
  hung check can't blind the watchdog). Pass -Mode loop for a single long-lived
  poller instead. Pass -AutoRestart to let it relaunch start_gammapulse.bat on a
  confirmed PROCESS DOWN.

  Remove later with:  Unregister-ScheduledTask -TaskName 'GammaPulseWatchdog' -Confirm:$false
#>
param(
  [ValidateSet('once', 'loop')] [string]$Mode = 'once',
  [switch]$AutoRestart,
  [int]$IntervalMinutes = 2,
  [string]$TaskName = 'GammaPulseWatchdog'
)

$ErrorActionPreference = 'Stop'
$repo   = Split-Path -Parent $PSScriptRoot           # C:\Dev\GammaPulse
$py     = Join-Path $repo '.venv\Scripts\python.exe'
$script = Join-Path $repo 'scripts\backend_watchdog.py'
$log    = Join-Path $repo 'logs\watchdog.log'

if (-not (Test-Path $py))     { throw "venv python not found at $py" }
if (-not (Test-Path $script)) { throw "watchdog not found at $script" }

$argList = "`"$script`" --$Mode"
if ($AutoRestart) { $argList += ' --auto-restart' }
# Append stdout/stderr to a rolling log (cmd wrapper so redirection works under Task Scheduler).
$cmdLine = "`"$py`" $argList >> `"$log`" 2>&1"

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c $cmdLine" -WorkingDirectory $repo

if ($Mode -eq 'once') {
  # Fire every IntervalMinutes, indefinitely. Omitting RepetitionDuration = forever (modern Windows).
  $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).Date.AddMinutes(1)) `
              -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
              -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
} else {
  # Long-lived loop: start at logon, auto-restart the watcher itself if it dies.
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
              -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
              -ExecutionTimeLimit ([TimeSpan]::Zero)
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
  -Description "GammaPulse external backend watchdog (#91): alerts on PROCESS DOWN / FLOW SILENT during RTH. Mode=$Mode AutoRestart=$AutoRestart" `
  -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' (Mode=$Mode, every $IntervalMinutes min, AutoRestart=$AutoRestart)."
Write-Host "Logs -> $log"
Write-Host "Test now:  python scripts\backend_watchdog.py --check"
Write-Host "Remove:    Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
