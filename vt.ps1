# Launcher: runs the CLI with every cache/model directory pointed inside this project.
$Root = $PSScriptRoot
$env:HF_HOME = Join-Path $Root "models\hf"
$env:HF_HUB_CACHE = Join-Path $Root "models\hf\hub"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:TORCH_HOME = Join-Path $Root "models\torch"
$env:XDG_CACHE_HOME = Join-Path $Root ".runtime\cache"
$env:PIP_CACHE_DIR = Join-Path $Root ".runtime\pip-cache"
$tmp = Join-Path $Root ".runtime\tmp"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$env:TMP = $tmp
$env:TEMP = $tmp
$env:PYTHONUTF8 = "1"
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error ".venv not found. Run setup.ps1 first."; exit 1 }
& $py -m video_transcribe @args
exit $LASTEXITCODE
