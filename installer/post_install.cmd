@echo off
setlocal
cd /d "%~dp0\.."
echo [Video Creator] Dang cai dat Python 3.11 va thu vien (uv sync)...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
  "$env:UV_SYSTEM_CERTS = 'true'; $env:UV_NATIVE_TLS = 'true'; " ^
  "$uvCmd = Get-Command uv -ErrorAction SilentlyContinue; " ^
  "$uv = if ($uvCmd) { $uvCmd.Source } else { @('.\tools\uv\uv.exe', \"$env:USERPROFILE\.local\bin\uv.exe\", \"$env:USERPROFILE\.cargo\bin\uv.exe\", \"$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe\") | Where-Object { Test-Path $_ } | Select-Object -First 1 }; " ^
  "if (-not $uv) { irm https://astral.sh/uv/install.ps1 | iex; $uv = \"$env:USERPROFILE\.local\bin\uv.exe\" }; " ^
  "& $uv sync --frozen; if ($LASTEXITCODE -ne 0) { & $uv sync }; exit $LASTEXITCODE"
if %ERRORLEVEL% NEQ 0 (
    echo [Loi] Cai dat thu vien that bai. Vui long kiem tra ket noi mang.
    pause
)
exit /b %ERRORLEVEL%
