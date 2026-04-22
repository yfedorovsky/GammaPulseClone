@echo off
:: GammaPulse Restart Script — Force Kill + Relaunch
:: Handles the "Ctrl+C doesn't work" problem by force-killing the uvicorn
:: process before starting a fresh one. Use this instead of manual Ctrl+C
:: during dev iterations.
::
:: Usage: double-click or run from terminal:  restart_gammapulse.bat

echo.
echo [restart] Finding uvicorn Python process...

:: Kill the Python process running uvicorn. Use WMIC to filter by command
:: line so we don't kill unrelated Python processes (e.g. Claude CLI).
for /f "tokens=2 delims==," %%p in ('wmic process where "name='python.exe' and commandline like '%%uvicorn%%'" get processid /value 2^>nul ^| find "="') do (
    echo [restart] Killing PID %%p ...
    taskkill /F /PID %%p 2>nul
)

:: Fallback: if wmic didn't find anything but we have a backend window
:: titled "GammaPulse Backend", close it by window title.
taskkill /F /FI "WINDOWTITLE eq GammaPulse Backend*" 2>nul

:: Give Windows a beat to release the port before we bind again
timeout /t 2 /nobreak >nul

echo [restart] Launching fresh backend...
cd /d C:\Dev\GammaPulse

start "GammaPulse Backend" cmd /k ".venv\Scripts\activate && uvicorn server.main:app --host 0.0.0.0 --port 8000"

echo.
echo [restart] Backend restart initiated.
echo [restart] Watch the new terminal window for startup logs.
echo [restart] Expect ~5-10 seconds before /api/health responds cleanly.
echo.
