@echo off
setlocal enabledelayedexpansion
title SightGuide Backend - Restart
color 0A

echo ============================================================
echo   SightGuide Backend - Restarting Server
echo ============================================================
echo.

:: Kill any existing uvicorn/python server on port 8000
echo [1/3] Stopping any existing server on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo Done.
echo.

:: Move to backend folder
cd /d "%~dp0backend"

:: Activate venv if it exists
echo [2/3] Activating virtual environment...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo Virtual environment activated.
) else (
    echo [WARN] No venv found - using system Python. Run setup_and_run.bat first if dependencies are missing.
)
echo.

:: Start server
echo [3/3] Starting FastAPI server...
echo.
echo ============================================================
echo   Server running on http://0.0.0.0:8000
echo   API docs:  http://localhost:8000/docs
echo   Health:    http://localhost:8000/api/health
echo   WebSocket: ws://YOUR_IP:8000/api/voice/ws
echo.
echo   Find your PC IP: run ipconfig in another terminal
echo   e.g. http://192.168.x.x:8000/api  (set this in app Settings)
echo ============================================================
echo.

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

pause
