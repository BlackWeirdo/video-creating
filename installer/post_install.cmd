@echo off
setlocal
cd /d "%~dp0\.."
echo [Video Creator] Syncing Python virtual environment...
if exist "tools\uv\uv.exe" (
    "tools\uv\uv.exe" sync --frozen
) else (
    uv sync --frozen
)
exit /b %ERRORLEVEL%
