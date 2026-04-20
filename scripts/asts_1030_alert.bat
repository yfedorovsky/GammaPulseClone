@echo off
REM One-off ASTS 10:30 AM alert — wire to Task Scheduler for Mon 2026-04-20 10:30 ET.
REM
REM Setup:
REM   1. taskschd.msc
REM   2. Create Basic Task → "ASTS 10:30 AM Alert"
REM   3. Trigger: One time, 2026-04-20 10:30 AM
REM   4. Action: Start a program
REM      Program:  C:\Dev\GammaPulse\scripts\asts_1030_alert.bat
REM      Start in: C:\Dev\GammaPulse
REM   5. Conditions: ☑ Wake the computer to run (if applicable)
REM
REM After it fires once, delete the task.
REM
REM Test it now:  double-click this .bat and check Telegram

setlocal
cd /d C:\Dev\GammaPulse
call .venv\Scripts\activate.bat

REM Load .env for TELEGRAM credentials
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if not "%%a"=="" if not "%%a:~0,1%"=="#" set "%%a=%%b"
)

python -X utf8 -m scripts.asts_1030_alert
endlocal
