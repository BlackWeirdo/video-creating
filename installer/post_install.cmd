@echo off
setlocal
cd /d "%~dp0\.."
echo [Video Creator V2] Dang thiet lap Python 3.11, FFmpeg, Node 24 va thu vien...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
  "$env:UV_SYSTEM_CERTS = 'true'; $env:UV_NATIVE_TLS = 'true'; " ^
  "if (-not (Test-Path '.\ffmpeg\bin\ffmpeg.exe') -and -not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and (Get-Command winget -ErrorAction SilentlyContinue)) { winget install --id Gyan.FFmpeg --source winget -e --silent --accept-source-agreements --accept-package-agreements }; " ^
  "if (-not (Test-Path '.\runtime\node\node.exe') -and -not (Get-Command node -ErrorAction SilentlyContinue) -and (Get-Command winget -ErrorAction SilentlyContinue)) { winget install --id OpenJS.NodeJS.LTS --source winget -e --silent --accept-source-agreements --accept-package-agreements }; " ^
  "$uvCmd = Get-Command uv -ErrorAction SilentlyContinue; " ^
  "$uv = if ($uvCmd) { $uvCmd.Source } else { @('.\tools\uv\uv.exe', \"$env:USERPROFILE\.local\bin\uv.exe\", \"$env:USERPROFILE\.cargo\bin\uv.exe\", \"$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe\") | Where-Object { Test-Path $_ } | Select-Object -First 1 }; " ^
  "if (-not $uv) { irm https://astral.sh/uv/install.ps1 | iex; $uv = \"$env:USERPROFILE\.local\bin\uv.exe\" }; " ^
  "& $uv sync --frozen; if ($LASTEXITCODE -ne 0) { & $uv sync }; exit $LASTEXITCODE"
if %ERRORLEVEL% NEQ 0 (
    echo [Loi] Cai dat thu vien Video Creator V2 that bai. Vui long kiem tra ket noi mang.
    pause
)
exit /b %ERRORLEVEL%
