@echo off
title SightGuide Local AI Server
cd /d "%~dp0"
echo ===================================================
echo        SIGHTGUIDE LOCAL AI BACKEND SERVER
echo ===================================================
echo.
echo Detecting your PC Wi-Fi IP Address...
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    set IP=%%a
    goto :found
)
:found
set IP=%IP: =%
echo.
echo ===================================================
echo Your Local Server is running on:
echo - Local PC: http://localhost:8000/api
echo - Phone Wi-Fi: http://%IP%:8000/api
echo ===================================================
echo.
echo IN SIGHTGUIDE APP ON PHONE:
echo 1. Open App -^> Go to Settings
echo 2. Enter Custom Backend Server URL: http://%IP%:8000/api
echo 3. Tap Save
echo.
echo Starting FastAPI Server...
python run_backend_local.py
pause
