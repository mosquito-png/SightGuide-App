@echo off
setlocal enabledelayedexpansion
title SightGuide Backend Setup & Run
color 0A

echo ============================================================
echo   SightGuide Backend - Auto Setup and Run
echo ============================================================
echo.

:: Move to backend folder
cd /d "%~dp0backend"

:: -----------------------------------------------------------
:: 1. Check Python
:: -----------------------------------------------------------
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.11+ from https://www.python.org/downloads/
    echo        Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
python --version
echo.

:: -----------------------------------------------------------
:: 2. Create virtual environment if it doesn't exist
:: -----------------------------------------------------------
echo [2/5] Setting up virtual environment...
if not exist "venv\Scripts\python.exe" (
    echo Creating new virtual environment...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo Virtual environment created successfully.
) else (
    echo Virtual environment already exists.
)
echo.

:: -----------------------------------------------------------
:: 3. Install / upgrade dependencies
:: -----------------------------------------------------------
echo [3/5] Installing dependencies (this may take a few minutes on first run)...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install some dependencies!
    pause
    exit /b 1
)
echo Dependencies installed successfully.
echo.

:: -----------------------------------------------------------
:: 4. Check / populate .env
:: -----------------------------------------------------------
echo [4/5] Checking environment configuration...
set ENV_FILE=%~dp0.env

:: Read .env size - if empty, populate with defaults
for %%A in ("%ENV_FILE%") do set ENV_SIZE=%%~zA
if "%ENV_SIZE%"=="0" (
    echo .env file is empty - writing default configuration...
    (
        echo # SightGuide Environment Configuration
        echo # Auto-generated defaults - fill in your real API keys below
        echo.
        echo # ---- AI Providers -----------------------------------------------
        echo GEMINI_API_KEY=
        echo GEMINI_MODEL=gemini-2.5-flash
        echo OPENAI_API_KEY=
        echo OPENAI_MODEL=gpt-4o-mini
        echo AI_TIMEOUT_SECONDS=8.0
        echo.
        echo SIGHTGUIDE_API_KEY=
        echo.
        echo # ---- Google Maps ------------------------------------------------
        echo GOOGLE_MAPS_API_KEY=
        echo GOOGLE_MAPS_MAP_ID=
        echo.
        echo # ---- Database ---------------------------------------------------
        echo MONGO_URI=mongodb://localhost:27017
        echo MONGO_DATABASE=sightguide
        echo.
        echo # ---- Redis (optional, falls back to in-memory if unavailable) ---
        echo REDIS_URL=redis://localhost:6379/0
        echo.
        echo # ---- App behaviour ----------------------------------------------
        echo ENVIRONMENT=development
        echo AUTH_ENABLED=false
        echo TOOL_TIMEOUT_SECONDS=8
        echo MAX_RETRIES=2
        echo.
        echo # ---- CORS origins (add your phone's local IP if needed) ---------
        echo CORS_ORIGINS=http://localhost:5173,http://localhost,http://127.0.0.1,capacitor://localhost,ionic://localhost,https://localhost
        echo.
        echo # ---- Frontend ---------------------------------------------------
        echo VITE_API_URL=http://localhost:8000/api
        echo VITE_GOOGLE_MAPS_API_KEY=
    ) > "%ENV_FILE%"
    echo Default .env written to %ENV_FILE%
    echo.
    echo *** IMPORTANT: Open .env and fill in your API keys if needed ***
    echo.
) else (
    echo .env file found with existing configuration.
)
echo.

:: -----------------------------------------------------------
:: 5. Start the server
:: -----------------------------------------------------------
echo [5/5] Starting FastAPI server...
echo.
echo ============================================================
echo   Server starting on http://0.0.0.0:8000
echo   API docs: http://localhost:8000/docs
echo   Health:   http://localhost:8000/api/health
echo.
echo   For phone access, use your PC's local IP:
echo   Find it with: ipconfig (look for IPv4 Address)
echo   e.g. http://192.168.x.x:8000
echo ============================================================
echo.

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

pause
