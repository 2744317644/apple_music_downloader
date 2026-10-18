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
REM The downloader itself now lives inside WSL (/opt/amdl-legacy/amdl), so it is
REM no longer shipped with the exe. Only the local helper tools are bundled.
if exist "%ROOT%\assets\ffmpeg.exe" (
    echo Found ffmpeg.exe - will bundle it.
) else (
    echo [WARN] assets\ffmpeg.exe not found - convert feature needs ffmpeg.
)
if exist "%ROOT%\assets\ffprobe.exe" (
    echo Found ffprobe.exe - will bundle it.
) else (
    echo [WARN] assets\ffprobe.exe not found - rename feature needs ffprobe.
)
echo OK.
echo.

REM ---- Build ----
echo [4/4] Building AppleMusicDownloader.exe...
echo.

REM The output exe cannot be overwritten while it is running, so close it first.
tasklist /FI "IMAGENAME eq AppleMusicDownloader.exe" 2>nul | find /I "AppleMusicDownloader.exe" >nul
if %ERRORLEVEL% equ 0 (
    echo Closing the running AppleMusicDownloader.exe...
    taskkill /IM AppleMusicDownloader.exe /F >nul 2>&1
    timeout /t 3 /nobreak >nul
)
if exist "%ROOT%\AppleMusicDownloader.exe" (
    move /y "%ROOT%\AppleMusicDownloader.exe" "%ROOT%\AppleMusicDownloader.exe.old" >nul 2>&1
    if exist "%ROOT%\AppleMusicDownloader.exe" (
        echo [ERROR] Cannot overwrite AppleMusicDownloader.exe - it is still in use.
        echo         Close it, or stop any antivirus scan, then run this script again.
        pause
        exit /b 1
    )
    echo Previous build saved as AppleMusicDownloader.exe.old
)

set "SPEC=%ROOT%\AppleMusicDownloader.spec"
> "%SPEC%" echo # -*- mode: python ; coding: utf-8 -*-
>> "%SPEC%" echo a = Analysis(
>> "%SPEC%" echo     [r'%ROOT%\apple_music_downloader_gui.py'],
>> "%SPEC%" echo     pathex=[],
>> "%SPEC%" echo     binaries=[],
>> "%SPEC%" echo     datas=[
>> "%SPEC%" echo         (r'%ROOT%\assets\app_icon.ico', r'assets'),
>> "%SPEC%" echo         (r'%ROOT%\assets\flac.exe', r'assets'),
if exist "%ROOT%\assets\ffmpeg.exe" >> "%SPEC%" echo         (r'%ROOT%\assets\ffmpeg.exe', r'assets'),
if exist "%ROOT%\assets\ffprobe.exe" >> "%SPEC%" echo         (r'%ROOT%\assets\ffprobe.exe', r'assets'),
>> "%SPEC%" echo         (r'%ROOT%\config.yaml.example', r'.'),
>> "%SPEC%" echo     ],
>> "%SPEC%" echo     hiddenimports=['PIL._tkinter_finder'],
>> "%SPEC%" echo     hookspath=[],
>> "%SPEC%" echo     hooksconfig={},
>> "%SPEC%" echo     runtime_hooks=[],
>> "%SPEC%" echo     excludes=[],
>> "%SPEC%" echo     noarchive=False,
>> "%SPEC%" echo     optimize=0,
>> "%SPEC%" echo )
>> "%SPEC%" echo pyz = PYZ(a.pure)
>> "%SPEC%" echo exe = EXE(
>> "%SPEC%" echo     pyz,
>> "%SPEC%" echo     a.scripts,
>> "%SPEC%" echo     a.binaries,
>> "%SPEC%" echo     a.datas,
>> "%SPEC%" echo     [],
>> "%SPEC%" echo     name='AppleMusicDownloader',
>> "%SPEC%" echo     debug=False,
>> "%SPEC%" echo     bootloader_ignore_signals=False,
>> "%SPEC%" echo     strip=False,
>> "%SPEC%" echo     upx=True,
>> "%SPEC%" echo     upx_exclude=[],
>> "%SPEC%" echo     runtime_tmpdir=None,
>> "%SPEC%" echo     console=False,
>> "%SPEC%" echo     disable_windowed_traceback=True,
>> "%SPEC%" echo     hide_console='hide-early',
>> "%SPEC%" echo     argv_emulation=False,
>> "%SPEC%" echo     target_arch=None,
>> "%SPEC%" echo     codesign_identity=None,
>> "%SPEC%" echo     entitlements_file=None,
>> "%SPEC%" echo     icon=[r'%ROOT%\assets\app_icon.ico'],
>> "%SPEC%" echo )

python -m PyInstaller --distpath "%ROOT%" --workpath "%ROOT%\build_temp" --log-level INFO "%SPEC%"
set "BUILD_RESULT=%ERRORLEVEL%"

echo.
if %BUILD_RESULT% equ 0 (
    echo ========================================
    echo  Build SUCCESS!
    echo  Output: %ROOT%\AppleMusicDownloader.exe
    echo ========================================
    if exist "%ROOT%\AppleMusicDownloader.exe.old" del /f /q "%ROOT%\AppleMusicDownloader.exe.old" >nul 2>&1
) else (
    echo ========================================
    echo  Build FAILED! Check errors above.
    echo ========================================
    if exist "%ROOT%\AppleMusicDownloader.exe.old" (
        move /y "%ROOT%\AppleMusicDownloader.exe.old" "%ROOT%\AppleMusicDownloader.exe" >nul 2>&1
        echo  Restored the previous AppleMusicDownloader.exe
    )
)

REM ---- Cleanup ----
if exist "%ROOT%\build_temp" rmdir /s /q "%ROOT%\build_temp"
if exist "%ROOT%\AppleMusicDownloader.spec" del "%ROOT%\AppleMusicDownloader.spec"

echo.
pause
exit /b
