@echo off
setlocal
cd /d "%~dp0\.."
echo [Video Creator V2] Dang kich hoat moi truong Offline (Python 3.11 + Node 24 + FFmpeg)...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0post_install.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo [Loi] Kich hoat moi truong Offline Video Creator V2 that bai.
    exit /b %ERRORLEVEL%
)
exit /b 0
