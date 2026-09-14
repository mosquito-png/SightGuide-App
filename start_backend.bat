@echo off
cd /d "%~dp0backend"
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)
echo.
echo Starting SightGuide backend API server on 0.0.0.0:8000...
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pause

