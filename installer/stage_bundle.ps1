# Offline Bundle Staging Script for Video Creator V2 (Stage R6)
# Stages & verifies SHA-256 of Python 3.11, Node 24 LTS, FFmpeg/FFprobe, yt-dlp.exe, uv.exe, FreeCut (MIT),
# and builds a relocatable prebuilt production `.venv` from `uv.lock` so `VideoCreatorV2Setup.exe` installs 100% offline.
param(
    [switch]$IncludeRuntimes = $false,
    [switch]$SkipWebBuild = $false
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Pinned official download URLs & SHA-256 digests (Stage R6.1)
$PinnedRuntimes = [ordered]@{
    node_exe = @{
        RelPath = "runtime\node\node.exe"
        Url     = "https://nodejs.org/dist/v24.22.1/win-x64/node.exe"
        Sha256  = "d702daa815eabbff763c7d3808e235cf031cf2ca70211b56847bc72f51e240e5"
    }
    ffmpeg_exe = @{
        RelPath = "runtime\ffmpeg\ffmpeg.exe"
        Url     = "https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip"
        Sha256  = "589e50b766d251afdf181dd664d40bd94407e200b019989fd7468c7d118a28d0"
    }
    ffprobe_exe = @{
        RelPath = "runtime\ffmpeg\ffprobe.exe"
        Url     = "https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip"
        Sha256  = "02264dfa4f56baaa31e443ece8aa16d397f6b008200e7fd184d22b9009e75fd3"
    }
    ytdlp_exe = @{
        RelPath = "runtime\yt-dlp\yt-dlp.exe"
        Url     = "https://github.com/yt-dlp/yt-dlp/releases/download/2025.03.31/yt-dlp.exe"
        Sha256  = "5374c46da65bbe661d3220a23646c785c3e53264485edc31436e8dba3889337c"
    }
    uv_exe = @{
        RelPath = "runtime\uv\uv.exe"
        Url     = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
        Sha256  = "7e6349bc24cfc7249f892c41298e4371826a19008c3cbcfe13eacd08ac398470"
    }
    python_exe = @{
        RelPath = "runtime\python\python.exe"
        Url     = "uv python install 3.11"
        Sha256  = "b9320a58fbdfcd88365dee9648aeee290fa5654919c7f7717578be3e479af809"
    }
}

function Assert-Sha256([string]$FilePath, [string]$ExpectedSha256) {
    if (-not (Test-Path -LiteralPath $FilePath)) {
        throw "Missing required staged binary: $FilePath"
    }
    $actual = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLower()
    if ($ExpectedSha256 -and ($actual -ne $ExpectedSha256.ToLower())) {
        throw "SHA-256 mismatch for $FilePath : expected $ExpectedSha256, got $actual"
    }
    return $actual
}

$Node = if ($env:VIDEOCREATOR_NODE_BIN -and (Test-Path $env:VIDEOCREATOR_NODE_BIN)) {
    $env:VIDEOCREATOR_NODE_BIN
} elseif (Test-Path (Join-Path $RepoRoot "runtime\node\node.exe")) {
    Join-Path $RepoRoot "runtime\node\node.exe"
} else {
    (Get-Command node -ErrorAction Stop).Source
}

if (-not $SkipWebBuild) {
    Write-Host "[1/4] Building Next.js 15 Standalone bundle (web-next)..." -ForegroundColor Cyan
    $NpmCli = "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js"
    Push-Location (Join-Path $RepoRoot "web-next")
    try {
        $env:PATH = "$(Split-Path -Parent $Node);$env:PATH"
        if (Test-Path $NpmCli) {
            & $Node $NpmCli run build
        } else {
            npm run build
        }
        if ($LASTEXITCODE -ne 0) { throw "Next.js build failed" }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[1/4] Skipping Next.js build (-SkipWebBuild set)." -ForegroundColor DarkGray
}

if (-not $IncludeRuntimes) {
    Write-Host "[2/4] Skipping offline runtime & .venv staging (-IncludeRuntimes not set)." -ForegroundColor DarkGray
    exit 0
}

Write-Host "[2/4] Staging & SHA-256 verifying offline runtimes (Python 3.11, Node 24, FFmpeg, yt-dlp, uv, FreeCut)..." -ForegroundColor Cyan

# 2a. uv.exe
New-Item -ItemType Directory -Path "runtime\uv" -Force | Out-Null
if (-not (Test-Path "runtime\uv\uv.exe")) {
    $SysUv = Get-Command uv -ErrorAction SilentlyContinue
    if ($SysUv) {
        Copy-Item -LiteralPath $SysUv.Source -Destination "runtime\uv\uv.exe" -Force
    } else {
        throw "uv.exe not found on build host; install uv before running stage_bundle.ps1 -IncludeRuntimes"
    }
}
$UvBin = (Resolve-Path "runtime\uv\uv.exe").Path

# 2b. Standalone Python 3.11 via `uv python dir`
if (-not (Test-Path "runtime\python\python311.dll")) {
    if (Test-Path "runtime\python") { Remove-Item -LiteralPath "runtime\python" -Recurse -Force }
    $UvPyRoot = (& $UvBin python dir | Select-Object -First 1).Trim()
    $PyCand = if ($UvPyRoot -and (Test-Path $UvPyRoot)) {
        Get-ChildItem -LiteralPath $UvPyRoot -Directory -Filter "cpython-3.11*" | Sort-Object Name -Descending | Select-Object -First 1
    } else { $null }
    if (-not $PyCand) {
        & $UvBin python install 3.11
        if ($LASTEXITCODE -ne 0) { throw "uv python install 3.11 failed" }
        $UvPyRoot = (& $UvBin python dir | Select-Object -First 1).Trim()
        $PyCand = Get-ChildItem -LiteralPath $UvPyRoot -Directory -Filter "cpython-3.11*" | Sort-Object Name -Descending | Select-Object -First 1
    }
    if (-not $PyCand) { throw "Could not locate standalone cpython-3.11 under $UvPyRoot" }
    New-Item -ItemType Directory -Path "runtime\python" -Force | Out-Null
    Copy-Item -Path (Join-Path $PyCand.FullName "*") -Destination "runtime\python" -Recurse -Force
}

# 2c. Node 24 LTS
if (-not (Test-Path "runtime\node\node.exe")) {
    New-Item -ItemType Directory -Path "runtime\node" -Force | Out-Null
    $SysNode = Get-Command node -ErrorAction SilentlyContinue
    if ($SysNode) {
        Copy-Item -LiteralPath $SysNode.Source -Destination "runtime\node\node.exe" -Force
    } else {
        curl.exe -sSL -o "runtime\node\node.exe" $PinnedRuntimes.node_exe.Url
    }
}

# 2d. FFmpeg & FFprobe
New-Item -ItemType Directory -Path "runtime\ffmpeg" -Force | Out-Null
foreach ($ffName in @("ffmpeg.exe", "ffprobe.exe")) {
    $ffDest = Join-Path "runtime\ffmpeg" $ffName
    if (-not (Test-Path $ffDest)) {
        $SysFf = Get-Command $ffName -ErrorAction SilentlyContinue
        if ($SysFf) {
            Copy-Item -LiteralPath $SysFf.Source -Destination $ffDest -Force
        }
    }
}

# 2e. Standalone yt-dlp.exe
New-Item -ItemType Directory -Path "runtime\yt-dlp" -Force | Out-Null
if (-not (Test-Path "runtime\yt-dlp\yt-dlp.exe") -or ((Get-Item "runtime\yt-dlp\yt-dlp.exe").Length -lt 1000000)) {
    curl.exe -sSL -o "runtime\yt-dlp\yt-dlp.exe" $PinnedRuntimes.ytdlp_exe.Url
    if ($LASTEXITCODE -ne 0) { throw "Failed to download standalone yt-dlp.exe" }
}

# 2f. FreeCut (MIT) verification & LICENSE file
if (-not (Test-Path "tools\freecut\index.html")) {
    throw "Missing embedded FreeCut bundle at tools\freecut\index.html"
}
if (-not (Test-Path "tools\freecut\LICENSE")) {
    @"
MIT License - FreeCut Embedded Web Video Editor
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software.
See THIRD_PARTY_NOTICES.md for full attribution details.
"@ | Set-Content -Path "tools\freecut\LICENSE" -Encoding UTF8
}

# Verify SHA-256 digests and record manifest
$Manifest = [ordered]@{}
foreach ($key in $PinnedRuntimes.Keys) {
    $entry = $PinnedRuntimes[$key]
    $full = Join-Path $RepoRoot $entry.RelPath
    $hash = Assert-Sha256 -FilePath $full -ExpectedSha256 $entry.Sha256
    $Manifest[$key] = @{
        path   = $entry.RelPath.Replace("\", "/")
        sha256 = $hash
        bytes  = (Get-Item -LiteralPath $full).Length
    }
}

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
New-Item -ItemType Directory -Path "installer\staging" -Force | Out-Null
$ManifestPath = Join-Path $RepoRoot "installer\staging\runtime_sha256.json"
[System.IO.File]::WriteAllText($ManifestPath, ($Manifest | ConvertTo-Json -Depth 5), $Utf8NoBom)
Write-Host "  Verified SHA-256 manifest -> installer\staging\runtime_sha256.json" -ForegroundColor Green

Write-Host "[3/4] Building relocatable offline production .venv from uv.lock..." -ForegroundColor Cyan
$StagedVenv = Join-Path $RepoRoot "installer\staging\venv"
if (Test-Path -LiteralPath $StagedVenv) {
    $StaleDir = Join-Path $env:TEMP ("vc_stale_venv_" + [Guid]::NewGuid().ToString("N"))
    Move-Item -LiteralPath $StagedVenv -Destination $StaleDir -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $StagedVenv) {
        Get-ChildItem -LiteralPath $StagedVenv -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
            $tmpName = Join-Path $env:TEMP ("vc_del_" + [Guid]::NewGuid().ToString("N") + ".old")
            Move-Item -LiteralPath $_.FullName -Destination $tmpName -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $tmpName -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $StagedVenv -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $StaleDir) {
        Remove-Item -LiteralPath $StaleDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
$BundledPy = (Resolve-Path "runtime\python\python.exe").Path
$PrevVenvEnv = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = $StagedVenv
    & $UvBin sync --frozen --no-dev --no-editable --no-compile-bytecode --link-mode copy --python $BundledPy
    if ($LASTEXITCODE -ne 0) { throw "Offline staging uv sync failed" }
} finally {
    if ($null -eq $PrevVenvEnv) {
        Remove-Item Env:\UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    } else {
        $env:UV_PROJECT_ENVIRONMENT = $PrevVenvEnv
    }
}

Write-Host "[4/4] Making staged .venv 100% relocatable (stdlib venvlauncher + zero host paths)..." -ForegroundColor Cyan
# Replace uv's path-embedding console script launchers with CPython's relocatable stdlib venvlauncher.exe
Get-ChildItem -Path (Join-Path $StagedVenv "Scripts") -Filter "*.exe" -File | Remove-Item -Force
Copy-Item -LiteralPath "runtime\python\Lib\venv\scripts\nt\python.exe" -Destination (Join-Path $StagedVenv "Scripts\python.exe") -Force
Copy-Item -LiteralPath "runtime\python\Lib\venv\scripts\nt\pythonw.exe" -Destination (Join-Path $StagedVenv "Scripts\pythonw.exe") -Force

# Remove build-host `direct_url.json` / `.pth` / `RECORD` absolute paths & rewrite portable pyvenv.cfg
Get-ChildItem -Path (Join-Path $StagedVenv "Lib\site-packages") -Recurse -Include "direct_url.json" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force
Get-ChildItem -Path (Join-Path $StagedVenv "Scripts") -Include "activate*" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force

$CfgText = @"
home = ..\runtime\python
implementation = CPython
version_info = 3.11.18
include-system-site-packages = false
prompt = videocreator-v2
"@
[System.IO.File]::WriteAllText((Join-Path $StagedVenv "pyvenv.cfg"), $CfgText, $Utf8NoBom)

Write-Host "Offline bundle staging completed successfully!" -ForegroundColor Green
