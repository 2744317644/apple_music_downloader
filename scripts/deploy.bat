@echo off
REM One-click wrapper: runs deploy.ps1 with the execution policy bypassed, so
REM the deployment works even when scripts are disabled system-wide.
setlocal

REM UTF-8 console: wsl.exe speaks UTF-8 (WSL_UTF8=1), and a Chinese Windows
REM console defaults to codepage 936, which would render it as mojibake.
chcp 65001 >nul 2>&1

set "SCRIPT=%~dp0deploy.ps1"

if not exist "%SCRIPT%" (
    echo [ERROR] deploy.ps1 not found next to this file.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo Deployment failed with exit code %RC%.
)
pause
exit /b %RC%