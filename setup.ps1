<#
.SYNOPSIS
    Bootstraps video-transcribe. Everything is installed INSIDE this project folder.

.DESCRIPTION
    Downloads into the project folder:
      .runtime\uv\        uv (Python package / interpreter manager)
      .runtime\python\    Python 3.12 (managed by uv)
      .runtime\ffmpeg\    ffmpeg + ffprobe (gyan.dev essentials build, includes libass)
      .venv\              project virtual environment with all Python packages
      fonts\              Noto Sans SC (Regular + Bold, SIL Open Font License)
      models\             Whisper / wav2vec2 models (only with -WithModels, otherwise on first run)

.PARAMETER WithModels
    Pre-download the Whisper and alignment models so later runs work offline.

.PARAMETER Model
    Whisper model to pre-download with -WithModels (tiny, base, small, medium, large-v3). Default: small.

.PARAMETER Dev
    Also install test dependencies (pytest).

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -WithModels -Model medium
#>
param(
    [switch]$WithModels,
    [string]$Model = "small",
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root    = $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$UvDir   = Join-Path $Runtime "uv"
$FfDir   = Join-Path $Runtime "ffmpeg"
$Fonts   = Join-Path $Root "fonts"
$TmpDir  = Join-Path $Runtime "tmp"

foreach ($d in @($Runtime, $UvDir, $FfDir, $Fonts, $TmpDir)) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

# Keep every cache inside the project.
$env:UV_CACHE_DIR            = Join-Path $Runtime "uv-cache"
$env:UV_PYTHON_INSTALL_DIR   = Join-Path $Runtime "python"
$env:UV_PYTHON_PREFERENCE    = "only-managed"
$env:UV_PROJECT_ENVIRONMENT  = Join-Path $Root ".venv"
$env:UV_TOOL_DIR             = Join-Path $Runtime "uv-tools"
$env:UV_NO_MODIFY_PATH       = "1"
$env:PIP_CACHE_DIR           = Join-Path $Runtime "pip-cache"
$env:TMP                     = $TmpDir
$env:TEMP                    = $TmpDir

function Get-File($Url, $Dest) {
    Write-Host "  downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
}

# ---------------------------------------------------------------- uv
$Uv = Join-Path $UvDir "uv.exe"
if (-not (Test-Path $Uv)) {
    Write-Host "[1/5] Installing uv into $UvDir"
    $zip = Join-Path $TmpDir "uv.zip"
    Get-File "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" $zip
    Expand-Archive -Path $zip -DestinationPath $UvDir -Force
    Remove-Item $zip
} else {
    Write-Host "[1/5] uv already present"
}

# ---------------------------------------------------------------- ffmpeg
$FfBin = Join-Path $FfDir "bin"
if (-not (Test-Path (Join-Path $FfBin "ffmpeg.exe"))) {
    Write-Host "[2/5] Installing ffmpeg into $FfDir"
    $zip = Join-Path $TmpDir "ffmpeg.zip"
    Get-File "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $zip
    $extract = Join-Path $TmpDir "ffmpeg-extract"
    if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    $inner = Get-ChildItem $extract -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path $FfBin | Out-Null
    Copy-Item (Join-Path $inner.FullName "bin\*") $FfBin -Force
    Remove-Item -Recurse -Force $extract, $zip
} else {
    Write-Host "[2/5] ffmpeg already present"
}

# ---------------------------------------------------------------- fonts
Write-Host "[3/5] Checking fonts"
$fontBase = "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC"
foreach ($f in @("NotoSansSC-Regular.otf", "NotoSansSC-Bold.otf")) {
    $dest = Join-Path $Fonts $f
    if (-not (Test-Path $dest)) { Get-File "$fontBase/$f" $dest }
}

# ---------------------------------------------------------------- python + packages
Write-Host "[4/5] Installing Python 3.12 and packages into .runtime\python and .venv"
Push-Location $Root
try {
    & $Uv python install 3.12
    if ($LASTEXITCODE -ne 0) { throw "uv python install failed" }
    $syncArgs = @("sync", "--python", "3.12")
    if ($Dev) { $syncArgs += @("--extra", "dev") }
    & $Uv @syncArgs
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
} finally {
    Pop-Location
}

# ---------------------------------------------------------------- models
if ($WithModels) {
    Write-Host "[5/5] Downloading models (whisper '$Model' + alignment models) into models\"
    & (Join-Path $Root "vt.cmd") download-models --model $Model
    if ($LASTEXITCODE -ne 0) { throw "model download failed" }
} else {
    Write-Host "[5/5] Skipping model download (models download on first run, or use -WithModels)"
}

Write-Host ""
Write-Host "Done. Try:"
Write-Host "  .\vt.cmd doctor"
Write-Host "  .\vt.cmd run path\to\video.mp4"
