@echo off
rem Launcher: runs the CLI with every cache/model directory pointed inside this project.
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "HF_HOME=%ROOT%\models\hf"
set "HF_HUB_CACHE=%ROOT%\models\hf\hub"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "TORCH_HOME=%ROOT%\models\torch"
set "XDG_CACHE_HOME=%ROOT%\.runtime\cache"
set "PIP_CACHE_DIR=%ROOT%\.runtime\pip-cache"
set "TMP=%ROOT%\.runtime\tmp"
set "TEMP=%ROOT%\.runtime\tmp"
set "PYTHONUTF8=1"
if not exist "%ROOT%\.runtime\tmp" mkdir "%ROOT%\.runtime\tmp"
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo .venv not found. Run setup.ps1 first. 1>&2
  exit /b 1
)
"%ROOT%\.venv\Scripts\python.exe" -m video_transcribe %*
exit /b %ERRORLEVEL%
