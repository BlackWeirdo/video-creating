# Optional runtime staging script to bundle offline Node 24 LTS, FFmpeg, yt-dlp, uv, and FreeCut before Inno Setup
param(
    [switch]$IncludeRuntimes = $false
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "[1/2] Building Next.js 15 Standalone bundle (web-next)..." -ForegroundColor Cyan
$Node = if (Test-Path "$env:LOCALAPPDATA\Programs\iCast\runtime\node\node.exe") {
    "$env:LOCALAPPDATA\Programs\iCast\runtime\node\node.exe"
} else {
    (Get-Command node -ErrorAction Stop).Source
}
$NpmCli = "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js"
Push-Location (Join-Path $RepoRoot "web-next")
try {
    & $Node $NpmCli run build
    if ($LASTEXITCODE -ne 0) { throw "Next.js build failed" }
} finally {
    Pop-Location
}

if ($IncludeRuntimes) {
    Write-Host "[2/2] Staging available local runtimes into runtime/ and ffmpeg/bin/..." -ForegroundColor Cyan
    $SrcNode = "$env:LOCALAPPDATA\Programs\iCast\runtime\node\node.exe"
    if (Test-Path $SrcNode) {
        New-Item -ItemType Directory -Path "runtime\node" -Force | Out-Null
        Copy-Item $SrcNode "runtime\node\node.exe" -Force
    }
    $SrcFfmpegDir = "$env:LOCALAPPDATA\Programs\iCast\runtime\ffmpeg"
    if (Test-Path (Join-Path $SrcFfmpegDir "ffmpeg.exe")) {
        New-Item -ItemType Directory -Path "ffmpeg\bin" -Force | Out-Null
        Copy-Item (Join-Path $SrcFfmpegDir "*.exe") "ffmpeg\bin\" -Force
    }
} else {
    Write-Host "[2/2] Skipping heavy binary copy (-IncludeRuntimes not set)." -ForegroundColor DarkGray
}
