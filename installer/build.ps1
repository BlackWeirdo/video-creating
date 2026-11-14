# PowerShell build script for Video Creator Windows Installer (Phase 08)
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "[1/2] Verifying uv.lock and local test suite..."
.\.venv\Scripts\pytest.exe -m local -q

$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -ne $Iscc) {
    Write-Host "[2/2] Building VideoCreatorSetup.exe via Inno Setup..."
    & $Iscc.Source "$PSScriptRoot\videocreator.iss"
} else {
    Write-Host "[2/2] ISCC.exe (Inno Setup) not installed on PATH; installer script staged at installer\videocreator.iss"
}
