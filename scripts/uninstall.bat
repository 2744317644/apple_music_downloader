@echo off
REM One-click uninstall wrapper: bypasses the execution policy and forces a
REM UTF-8 console so wsl.exe output is readable.
setlocal

chcp 65001 >nul 2>&1

set "SCRIPT=%~dp0uninstall.ps1"

if not exist "%SCRIPT%" (
    echo [ERROR] uninstall.ps1 not found next to this file.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo Uninstall exited with code %RC%.
)
pause
exit /b %RC%