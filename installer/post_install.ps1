# Offline Post-Install Activation Script for Video Creator V2 (100% Offline, Zero Network Calls)
$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
Set-Location $AppRoot

$PyHome    = Join-Path $AppRoot "runtime\python"
$VenvPy    = Join-Path $AppRoot ".venv\Scripts\python.exe"
$NodeExe   = Join-Path $AppRoot "runtime\node\node.exe"
$FfmpegExe = Join-Path $AppRoot "runtime\ffmpeg\ffmpeg.exe"

foreach ($req in @((Join-Path $PyHome "python.exe"), $VenvPy, $NodeExe, $FfmpegExe)) {
    if (-not (Test-Path -LiteralPath $req)) {
        throw "Thieu tep runtime dong goi: $req"
    }
}

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$CfgLines = @(
    "home = $PyHome",
    "implementation = CPython",
    "version_info = 3.11.18",
    "include-system-site-packages = false",
    "prompt = videocreator-v2"
) -join "`r`n"
[System.IO.File]::WriteAllText((Join-Path $AppRoot ".venv\pyvenv.cfg"), "$CfgLines`r`n", $Utf8NoBom)

$env:PATH = @(
    (Join-Path $AppRoot "runtime\ffmpeg"),
    (Join-Path $AppRoot "runtime\node"),
    (Join-Path $AppRoot "runtime\yt-dlp"),
    (Join-Path $AppRoot "runtime\uv"),
    $PyHome
) -join ";"
$env:PYTHONPATH = Join-Path $AppRoot "src"
$env:PYTHONIOENCODING = "utf-8"

& $VenvPy -c "import videocreator, onnxruntime, ctranslate2, faster_whisper; print('VideoCreatorV2 offline runtime ready:', videocreator.__version__)"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
exit 0
