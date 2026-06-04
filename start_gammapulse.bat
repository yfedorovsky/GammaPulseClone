@echo off
:: GammaPulse Auto-Start Script
:: Add to Windows Task Scheduler: trigger at logon or 9:00 AM ET
:: Action: Start a program -> C:\Dev\GammaPulse\start_gammapulse.bat

:: 2026-06-02 PM: force Python to UTF-8 stdout encoding. Otherwise
:: Windows cp1252 console crashes print() statements containing em-dashes,
:: bullet points, or emoji. Caused "phase2 resubscribe error: charmap codec
:: can't encode" log spam tonight even though subscriptions worked fine.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo Starting GammaPulse...
cd /d C:\Dev\GammaPulse

:: Activate venv and start backend
:: Output redirected to logs\backend.log to avoid Windows cmd QuickEdit Mode
:: blocking Python's print() when the console buffer fills or the user
:: accidentally clicks the window (which pauses output and deadlocks the
:: async event loop). Tail with: Get-Content logs\backend.log -Wait
start "GammaPulse Backend" cmd /k ".venv\Scripts\activate && uvicorn server.main:app --host 0.0.0.0 --port 8000 > logs\backend.log 2>&1"

:: Wait for backend to initialize
timeout /t 5 /nobreak

:: Start frontend dev server
start "GammaPulse Frontend" cmd /k "cd web && npm run dev"

echo GammaPulse started. Backend: http://localhost:8000 Frontend: http://localhost:5173
