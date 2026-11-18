# PowerShell build script for Video Creator Windows Installer
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Find-Iscc {
    $cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $paths = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    return ($paths | Where-Object { Test-Path $_ } | Select-Object -First 1)
}

$Iscc = Find-Iscc
if (-not $Iscc -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "[1/2] Dang cai Inno Setup 6 qua winget de dong goi VideoCreatorSetup.exe..." -ForegroundColor Cyan
    winget install --id JRSoftware.InnoSetup -e --silent --accept-source-agreements --accept-package-agreements
    $Iscc = Find-Iscc
}

if ($Iscc) {
    Write-Host "[2/2] Dang dong goi installer\dist\VideoCreatorSetup.exe..." -ForegroundColor Cyan
    & $Iscc "$PSScriptRoot\videocreator.iss"
} else {
    Write-Host "Khong tim thay Inno Setup (ISCC.exe); hay dung truc tiep installer\Install-VideoCreator.cmd tren may khac." -ForegroundColor Yellow
}
