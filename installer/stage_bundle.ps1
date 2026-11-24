# Runtime staging script to bundle offline Node 24 LTS, FFmpeg, yt-dlp, uv, and FreeCut before Inno Setup
param(
    [switch]$IncludeRuntimes = $false
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "[1/2] Building Next.js 15 Standalone bundle (web-next)..." -ForegroundColor Cyan
$Node = if ($env:VIDEOCREATOR_NODE_BIN -and (Test-Path $env:VIDEOCREATOR_NODE_BIN)) {
    $env:VIDEOCREATOR_NODE_BIN
} elseif (Test-Path (Join-Path $RepoRoot "runtime\node\node.exe")) {
    Join-Path $RepoRoot "runtime\node\node.exe"
} else {
    (Get-Command node -ErrorAction Stop).Source
}
$NpmCli = "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js"
Push-Location (Join-Path $RepoRoot "web-next")
try {
    if (Test-Path $NpmCli) {
        & $Node $NpmCli run build
    } else {
        npm run build
    }
    if ($LASTEXITCODE -ne 0) { throw "Next.js build failed" }
} finally {
    Pop-Location
}

if ($IncludeRuntimes) {
    Write-Host "[2/2] Verifying staged runtimes in runtime/ and tools/..." -ForegroundColor Cyan
    if (-not (Test-Path "runtime\node\node.exe")) {
        $SysNode = Get-Command node -ErrorAction SilentlyContinue
        if ($SysNode) {
            New-Item -ItemType Directory -Path "runtime\node" -Force | Out-Null
            Copy-Item $SysNode.Source "runtime\node\node.exe" -Force
        }
    }
    if (-not (Test-Path "runtime\ffmpeg\ffmpeg.exe")) {
        $SysFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
        if ($SysFfmpeg) {
            New-Item -ItemType Directory -Path "runtime\ffmpeg" -Force | Out-Null
            Copy-Item $SysFfmpeg.Source "runtime\ffmpeg\ffmpeg.exe" -Force
        }
    }
} else {
    Write-Host "[2/2] Skipping runtime copy (-IncludeRuntimes not set)." -ForegroundColor DarkGray
}
