@echo off
REM Weekend research runner — designed for Windows Task Scheduler.
REM Schedule: Saturday 10:00 AM ET (after IBD weekend paper publishes ~8 AM)
REM
REM Setup:
REM   1. Open Task Scheduler (taskschd.msc)
REM   2. Create Basic Task → "GammaPulse Weekend Research"
REM   3. Trigger: Weekly, Saturday, 10:00 AM
REM   4. Action: Start a program
REM      Program:  C:\Dev\GammaPulse\scripts\run_weekend_research.bat
REM      Start in: C:\Dev\GammaPulse
REM   5. Conditions: (optional) "Wake the computer to run"
REM
REM Output: docs\research\weekend_YYYY-MM-DD.md
REM Log:    %USERPROFILE%\.gammapulse\weekend_research.log

setlocal

cd /d C:\Dev\GammaPulse

REM Activate venv
call .venv\Scripts\activate.bat

REM Load .env (ANTHROPIC_API_KEY)
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if not "%%a"=="" if not "%%a:~0,1%"=="#" set "%%a=%%b"
)

REM Ensure log directory exists
if not exist "%USERPROFILE%\.gammapulse" mkdir "%USERPROFILE%\.gammapulse"

REM Run with timestamp in log
echo ===== Weekend research run: %DATE% %TIME% ===== >> "%USERPROFILE%\.gammapulse\weekend_research.log"
python -X utf8 -m scripts.weekend_research >> "%USERPROFILE%\.gammapulse\weekend_research.log" 2>&1

REM Optional: also refresh the IBD groups module from last week's paper
REM (manual step — you edit server\ibd_groups.py + ibd_sector_leaders.py by hand)

echo Run complete at %DATE% %TIME% >> "%USERPROFILE%\.gammapulse\weekend_research.log"

endlocal
