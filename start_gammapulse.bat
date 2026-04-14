@echo off
:: GammaPulse Auto-Start Script
:: Add to Windows Task Scheduler: trigger at logon or 9:00 AM ET
:: Action: Start a program -> C:\Dev\GammaPulse\start_gammapulse.bat

echo Starting GammaPulse...
cd /d C:\Dev\GammaPulse

:: Activate venv and start backend
start "GammaPulse Backend" cmd /k ".venv\Scripts\activate && uvicorn server.main:app --host 0.0.0.0 --port 8000"

:: Wait for backend to initialize
timeout /t 5 /nobreak

:: Start frontend dev server
start "GammaPulse Frontend" cmd /k "cd web && npm run dev"

echo GammaPulse started. Backend: http://localhost:8000 Frontend: http://localhost:5173
