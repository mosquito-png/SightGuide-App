@echo off
cd /d "%~dp0frontend"
if not exist node_modules (
    echo Installing dependencies...
    npm install --quiet
)
echo.
echo Starting SightGuide frontend dev server on local network...
npm run dev -- --host 0.0.0.0 --port 5173
pause

