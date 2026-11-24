# Optional Nuitka `.pyd` compilation script for Video Creator V2 core modules
# Compiles selected pure-Python business modules into binary `.pyd` extensions before Inno Setup packaging.
param(
    [string]$PythonExe = ".venv\Scripts\python.exe",
    [string]$OutDir = "build\nuitka"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path $PythonExe)) {
    throw "Python interpreter not found at '$PythonExe'. Run 'uv sync' first."
}

$HasNuitka = & $PythonExe -c "import importlib.util; print('1' if importlib.util.find_spec('nuitka') else '0')"
if ($HasNuitka.Trim() -ne "1") {
    Write-Host "[Nuitka] Nuitka chua duoc cai dat trong venv. Cai dat bang: uv pip install nuitka ordered-set zstandard" -ForegroundColor Yellow
    exit 1
}

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$Targets = @(
    @{ Source = "src\videocreator\workspaces.py"; DestSub = "videocreator" },
    @{ Source = "src\videocreator\autopilot.py"; DestSub = "videocreator" },
    @{ Source = "src\videocreator\onboarding.py"; DestSub = "videocreator" },
    @{ Source = "src\videocreator\pipeline\restyle.py"; DestSub = "videocreator\pipeline" },
    @{ Source = "src\videocreator\pipeline\workflow_engine.py"; DestSub = "videocreator\pipeline" }
)

foreach ($Target in $Targets) {
    $DestPath = Join-Path $OutDir $Target.DestSub
    New-Item -ItemType Directory -Path $DestPath -Force | Out-Null
    Write-Host "[Nuitka] Compiling $($Target.Source) -> $DestPath ..." -ForegroundColor Cyan
    & $PythonExe -m nuitka --module --no-pyi-file --remove-output --output-dir="$DestPath" "$($Target.Source)"
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka compilation failed for $($Target.Source)"
    }
}

Write-Host "[Nuitka] Hoan tat bien dich .pyd vao '$OutDir'." -ForegroundColor Green
