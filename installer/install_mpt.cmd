@echo off
setlocal
REM Installs pinned MoneyPrinterTurbo v1.3.9 into tools\mpt with its own venv and removes default songs (FR-REN-04, FR-REN-08).

set "MPT_VERSION=v1.3.9"
set "MPT_DIR=%~dp0..\tools\mpt"

echo [Video Creator] Installing MoneyPrinterTurbo %MPT_VERSION% into "%MPT_DIR%"...
if not exist "%MPT_DIR%" (
    git clone --branch %MPT_VERSION% --depth 1 https://github.com/harry0703/MoneyPrinterTurbo.git "%MPT_DIR%"
)

if exist "%MPT_DIR%\resource\songs" (
    echo [Video Creator] Removing default bundled songs directory to enforce user-supplied music policy (FR-REN-08)...
    rmdir /s /q "%MPT_DIR%\resource\songs"
)

pushd "%MPT_DIR%"
uv sync --frozen
popd

echo [Video Creator] MoneyPrinterTurbo %MPT_VERSION% installation complete.
endlocal
