@echo off
cd /d "%~dp0backend"
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)
echo.
echo ===== Starting Backend =====
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

