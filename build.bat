@echo off
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"
title Apple Music Downloader - Build

echo ========================================
echo  Apple Music Downloader - Build Script
echo ========================================
echo.

REM ---- Check Python ----
echo [1/4] Checking Python...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Python not found. Attempting to install via winget...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo Failed to install Python automatically.
        echo Please install Python 3.7+ from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo Python installed. Please restart this script.
    pause
    exit /b 0
)
python --version
echo OK.
echo.

REM ---- Check pip packages ----
echo [2/4] Installing Python packages...
python -m pip install -r "%ROOT%\requirements.txt" --quiet
echo OK.
echo.

REM ---- Verify assets ----
echo [3/4] Checking assets...
if not exist "%ROOT%\assets\Wrapper\Dockerfile" (
    echo [ERROR] assets\Wrapper\Dockerfile not found!
    pause
    exit /b 1
)
if not exist "%ROOT%\assets\apple-music-downloader\Dockerfile" (
    echo [ERROR] assets\apple-music-downloader\Dockerfile not found!
    pause
    exit /b 1
)
echo OK.
echo.

REM ---- Build ----
echo [4/4] Building AppleMusicDownloader.exe...

set "SPEC=%ROOT%\AppleMusicDownloader.spec"
(
echo # -*- mode: python ; coding: utf-8 -*-
echo a = Analysis(
echo     [r'%ROOT%\apple_music_downloader_gui.py'],
echo     pathex=[],
echo     binaries=[],
echo     datas=[
echo         (r'%ROOT%\assets\Wrapper', r'assets\Wrapper'^),
echo         (r'%ROOT%\assets\apple-music-downloader', r'assets\apple-music-downloader'^),
echo         (r'%ROOT%\assets\app_icon.ico', r'assets\app_icon.ico'^),
echo     ],
echo     hiddenimports=['PIL._tkinter_finder'],
echo     hookspath=[],
echo     hooksconfig={},
echo     runtime_hooks=[],
echo     excludes=[],
echo     noarchive=False,
echo     optimize=0,
echo ^)
echo pyz = PYZ(a.pure^)
echo exe = EXE(
echo     pyz,
echo     a.scripts,
echo     a.binaries,
echo     a.datas,
echo     [],
echo     name='AppleMusicDownloader',
echo     debug=False,
echo     bootloader_ignore_signals=False,
echo     strip=False,
echo     upx=True,
echo     upx_exclude=[],
echo     runtime_tmpdir=None,
echo     console=False,
echo     disable_windowed_traceback=True,
echo     hide_console='hide-early',
echo     argv_emulation=False,
echo     target_arch=None,
echo     codesign_identity=None,
echo     entitlements_file=None,
echo     icon=[r'%ROOT%\assets\app_icon.ico'],
echo ^)
) > "%SPEC%"

python -m PyInstaller --distpath "%ROOT%" --workpath "%ROOT%\build_temp" --log-level INFO "%SPEC%"
set "BUILD_RESULT=%ERRORLEVEL%"

echo.
if %BUILD_RESULT% equ 0 (
    echo ========================================
    echo  Build SUCCESS!
    echo  Output: %ROOT%\AppleMusicDownloader.exe
    echo ========================================
) else (
    echo ========================================
    echo  Build FAILED! Check errors above.
    echo ========================================
)

REM ---- Cleanup ----
if exist "%ROOT%\build_temp" rmdir /s /q "%ROOT%\build_temp"
if exist "%ROOT%\AppleMusicDownloader.spec" del "%ROOT%\AppleMusicDownloader.spec"

echo.
pause
exit /b
