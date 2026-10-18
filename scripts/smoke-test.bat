@echo off
REM One-click wrapper: bypasses the execution policy so the smoke test runs on
REM machines where scripts are disabled.
setlocal

chcp 65001 >nul 2>&1

set "SCRIPT=%~dp0smoke-test.ps1"

if not exist "%SCRIPT%" (
    echo [ERROR] smoke-test.ps1 not found next to this file.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"

echo.
pause
exit /b %RC%