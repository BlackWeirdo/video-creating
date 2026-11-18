@echo off
setlocal
cd /d "%~dp0\.."
echo [Video Creator] Setting up Python virtual environment (uv sync)...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; " ^
  "$uvCmd = Get-Command uv -ErrorAction SilentlyContinue; " ^
  "$uv = if ($uvCmd) { $uvCmd.Source } else { @('.\tools\uv\uv.exe', \"$env:USERPROFILE\.local\bin\uv.exe\", \"$env:USERPROFILE\.cargo\bin\uv.exe\", \"$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe\") | Where-Object { Test-Path $_ } | Select-Object -First 1 }; " ^
  "if (-not $uv) { irm https://astral.sh/uv/install.ps1 | iex; $uv = \"$env:USERPROFILE\.local\bin\uv.exe\" }; " ^
  "& $uv sync --frozen; exit $LASTEXITCODE"
exit /b %ERRORLEVEL%
