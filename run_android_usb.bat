@echo off
setlocal

set ROOT_DIR=%~dp0
set ADB=%ROOT_DIR%.tools\android-sdk\platform-tools\adb.exe
set JAVA_HOME=%ROOT_DIR%.tools\jdk21\jdk-21.0.12.1+1
set PATH=%JAVA_HOME%\bin;%PATH%
set APK_PATH=%ROOT_DIR%frontend\android\app\build\outputs\apk\debug\app-debug.apk

echo ========================================================
echo   SightGuide - USB Debugging Deployer
echo ========================================================
echo.

if not exist "%ADB%" (
    echo [ERROR] ADB not found at %ADB%
    pause
    exit /b 1
)

echo [1/5] Checking connected Android devices...
"%ADB%" devices
echo.

echo [2/5] Setting up USB Reverse Port Forwarding (8000 -^> 8000)...
"%ADB%" reverse tcp:8000 tcp:8000
echo   [OK] USB Reverse Proxy active: Phone localhost:8000 forwards to PC port 8000!
echo.

echo [3/5] Building latest Frontend and syncing Capacitor...
cd /d "%ROOT_DIR%frontend"
call npm run build
call npx cap sync android

echo.
echo [4/5] Building Android Debug APK...
cd /d "%ROOT_DIR%frontend\android"
call gradlew.bat assembleDebug
if errorlevel 1 (
    echo [ERROR] Gradle build failed.
    cd /d "%ROOT_DIR%"
    pause
    exit /b 1
)

echo.
echo [5/5] Installing and Launching SightGuide on your phone...
cd /d "%ROOT_DIR%"
if exist "%APK_PATH%" (
    "%ADB%" install -r "%APK_PATH%"
    echo.
    echo Launching SightGuide on phone...
    "%ADB%" shell am start -n com.sightguide.app/com.sightguide.app.MainActivity
    echo.
    echo ========================================================
    echo   SightGuide successfully installed and launched!
    echo   Make sure backend is running on your PC (port 8000).
    echo ========================================================
) else (
    echo [ERROR] APK not found at %APK_PATH%
)

pause
