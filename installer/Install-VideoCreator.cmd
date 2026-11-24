@echo off
title Cai dat Video Creator V2
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$s = (Get-Content -LiteralPath '%~f0' -Encoding UTF8 | Select-Object -Skip 5) -join [Environment]::NewLine; Invoke-Expression $s"
if %ERRORLEVEL% NEQ 0 pause
exit /b %ERRORLEVEL%
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:UV_SYSTEM_CERTS = "true"
$env:UV_NATIVE_TLS = "true"
$InstallDir = "$env:LOCALAPPDATA\Programs\VideoCreatorV2"
$RepoUrl = "https://github.com/BlackWeirdo/video-creating.git"
$ZipUrl = "https://github.com/BlackWeirdo/video-creating/archive/refs/heads/v2.zip"

function Refresh-SessionPath {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
}

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "   CAI DAT TU DONG VIDEO CREATOR (WINDOWS 10/11)    " -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan

# 1. Kiem tra va cai FFmpeg + Node.js LTS qua winget neu may chua co
Refresh-SessionPath
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and -not (Test-Path "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe")) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "[1/5] Dang cai dat FFmpeg..." -ForegroundColor Yellow
        winget install --id Gyan.FFmpeg --source winget -e --silent --accept-source-agreements --accept-package-agreements
        Refresh-SessionPath
    }
} else {
    Write-Host "[1/5] FFmpeg da san sang." -ForegroundColor Green
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "[2/5] Dang cai dat Node.js LTS (ho tro Studio Remotion)..." -ForegroundColor Yellow
        winget install --id OpenJS.NodeJS.LTS --source winget -e --silent --accept-source-agreements --accept-package-agreements
        Refresh-SessionPath
    }
} else {
    Write-Host "[2/5] Node.js da san sang." -ForegroundColor Green
}

# 2. Dong phien Video Creator dang chay (neu dang cap nhat)
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallDir, [System.StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# 3. Tai hoac cap nhat ma nguon Video Creator
Write-Host "[3/5] Dang tai ma nguon Video Creator vao $InstallDir ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
if (Get-Command git -ErrorAction SilentlyContinue) {
    Set-Location $InstallDir
    if (Test-Path "$InstallDir\.git") {
        if (git status --porcelain) { git stash }
        git pull origin main
    } else {
        git init
        git remote add origin $RepoUrl
        git fetch origin main
        git reset --hard origin/main
    }
} else {
    $TmpZip = Join-Path $env:TEMP "videocreator-main.zip"
    $TmpExtract = Join-Path $env:TEMP "videocreator-extract"
    if (Test-Path $TmpExtract) { Remove-Item $TmpExtract -Recurse -Force }
    Invoke-WebRequest -Uri $ZipUrl -OutFile $TmpZip -UseBasicParsing
    Expand-Archive -LiteralPath $TmpZip -DestinationPath $TmpExtract -Force
    $Inner = Get-ChildItem -LiteralPath $TmpExtract -Directory | Select-Object -First 1
    Copy-Item -Path (Join-Path $Inner.FullName "*") -Destination $InstallDir -Recurse -Force
    Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
    Remove-Item $TmpExtract -Recurse -Force -ErrorAction SilentlyContinue
    Set-Location $InstallDir
}

# 4. Cai uv + Python 3.11 + thu vien du an
Write-Host "[4/5] Dang cai dat Python 3.11 va thu vien (uv sync)..." -ForegroundColor Yellow
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
$uv = if ($uvCmd) { $uvCmd.Source } else {
    @("$InstallDir\tools\uv\uv.exe", "$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $uv) {
    irm https://astral.sh/uv/install.ps1 | iex
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
}
Set-Location $InstallDir
& $uv sync --frozen
if ($LASTEXITCODE -ne 0) { & $uv sync }

# 5. Tao Shortcut tren Desktop va Start Menu
Write-Host "[5/5] Dang tao bieu tuong Video Creator V2 ngoai Desktop..." -ForegroundColor Yellow
$WshShell = New-Object -ComObject WScript.Shell
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$StartMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "Video Creator V2"
New-Item -ItemType Directory -Path $StartMenuDir -Force | Out-Null

foreach ($ShortcutPath in @((Join-Path $DesktopDir "Video Creator V2.lnk"), (Join-Path $StartMenuDir "Video Creator V2.lnk"))) {
    $Sc = $WshShell.CreateShortcut($ShortcutPath)
    $Sc.TargetPath = "$env:SystemRoot\System32\wscript.exe"
    $Sc.Arguments = "`"$InstallDir\installer\launch.vbs`""
    $Sc.WorkingDirectory = $InstallDir
    if (Test-Path "$InstallDir\installer\videocreator.ico") {
        $Sc.IconLocation = "$InstallDir\installer\videocreator.ico,0"
    }
    $Sc.Description = "Video Creator V2"
    $Sc.Save()
}

Write-Host ""
Write-Host "=== CAI DAT HOAN TAT! DANG MO VIDEO CREATOR V2... ===" -ForegroundColor Green
Start-Process -FilePath "$env:SystemRoot\System32\wscript.exe" -ArgumentList "`"$InstallDir\installer\launch.vbs`"" -WorkingDirectory $InstallDir
Start-Sleep -Seconds 3
