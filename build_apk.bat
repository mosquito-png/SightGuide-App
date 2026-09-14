@echo off
setlocal enabledelayedexpansion
title SightGuide - Build New APK
color 0B

echo ============================================================
echo   SightGuide - Build Fresh APK with Voice Fix
echo ============================================================
echo.
if exist "%~dp0.tools\jdk21\jdk-21.0.12.1+1" (
    set "JAVA_HOME=%~dp0.tools\jdk21\jdk-21.0.12.1+1"
    set "PATH=%~dp0.tools\jdk21\jdk-21.0.12.1+1\bin;!PATH!"
) else if exist "%~dp0.tools\jdk17\jdk-17.0.20.1+1" (
    set "JAVA_HOME=%~dp0.tools\jdk17\jdk-17.0.20.1+1"
    set "PATH=%~dp0.tools\jdk17\jdk-17.0.20.1+1\bin;!PATH!"
)

cd /d "%~dp0frontend"

:: Check node
echo [1/5] Checking Node.js...
node --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js not found! Install from https://nodejs.org
    pause
    exit /b 1
)
node --version
echo.

:: Install npm deps if needed
echo [2/5] Installing npm dependencies...
npm install
if %ERRORLEVEL% neq 0 (
    echo [ERROR] npm install failed!
    pause
    exit /b 1
)
echo.

:: Build vite
echo [3/5] Building web app (vite build)...
npm run build
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Vite build failed!
    pause
    exit /b 1
)
echo Build complete!
echo.

:: Prevent recursive nesting of APK into Android assets
if exist "dist\sightguide.apk" del /q /f "dist\sightguide.apk"
if exist "android\app\src\main\assets\public\sightguide.apk" del /q /f "android\app\src\main\assets\public\sightguide.apk"

:: Sync capacitor
echo [4/5] Syncing Capacitor to Android...
npx cap sync android
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Capacitor sync failed!
    pause
    exit /b 1
)
echo Sync complete!
echo.

:: Build APK with Gradle
echo [5/5] Building Android debug APK...
cd android
call gradlew.bat assembleDebug
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Gradle build failed! Make sure Android SDK is installed.
    echo        Install Android Studio from https://developer.android.com/studio
    cd ..
    pause
    exit /b 1
)
cd ..

:: Copy APK to public folder for download
set APK_SRC=android\app\build\outputs\apk\debug\app-debug.apk
set APK_DST=public\sightguide.apk
if exist "%APK_SRC%" (
    copy /Y "%APK_SRC%" "%APK_DST%" >nul
    echo.
    echo ============================================================
    echo   APK built and saved to:
    echo   %~dp0frontend\public\sightguide.apk
    echo.
    echo   The backend serves it at:
    echo   http://YOUR_PC_IP:8000/sightguide.apk
    echo   http://YOUR_PC_IP:8000/download/apk
    echo ============================================================
) else (
    echo [WARN] APK not found at expected path: %APK_SRC%
)

echo.
pause
