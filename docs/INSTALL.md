# Installation

Everything the tool needs is installed **inside the project folder**. Setup does not touch the system Python, system PATH, `%APPDATA%`, `%LOCALAPPDATA%`, `~/.cache` or any other global location. Delete the folder and the tool is gone.

## Requirements

- Windows 10/11 x64 (main target), Linux x86_64/arm64 or macOS
- An internet connection for setup and the first run (models download). Later runs work offline.
- About 3–5 GB of free disk space (see [Disk usage](#disk-usage))
- No GPU needed. Everything runs on the CPU.
- **No** pre-installed Python, ffmpeg or uv. Setup downloads its own copies.

## Windows

Open PowerShell in the project folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Options:

| Option | Meaning |
|---|---|
| `-WithModels` | also download the models now, so the first real run needs no internet |
| `-Model medium` | which Whisper model `-WithModels` downloads (default `small`) |
| `-Dev` | also install `pytest` for running the tests |

Example for a fully offline-ready setup with a more accurate model:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -WithModels -Model medium
```

The steps that `setup.ps1` runs:

1. Downloads **uv** (a Python/package manager) into `.runtime\uv\`.
2. Downloads **ffmpeg + ffprobe** (gyan.dev "essentials" build, which includes libass, x264, VP9 and Opus) into `.runtime\ffmpeg\bin\`.
3. Downloads the **Noto Sans SC** font (Regular and Bold) into `fonts\`.
4. Installs **Python 3.12** into `.runtime\python\` and every Python package into `.venv\`. PyTorch comes from the CPU-only package index, which avoids about 2.5 GB of CUDA files.
5. Optionally downloads the models into `models\`.

You can run setup again at any time. Steps that are already done are skipped.

Check the installation:

```powershell
.\vt.cmd doctor
```

Every line should say `OK`. `doctor` also confirms that the Python executable, ffmpeg and all cache folders are inside the project.

## Linux / macOS

```bash
chmod +x setup.sh vt.sh
./setup.sh                    # add --with-models small  and/or  --dev
./vt.sh doctor
```

On Linux x86_64 a static ffmpeg build is downloaded into `.runtime/ffmpeg/bin`. On other platforms, copy an `ffmpeg` and `ffprobe` built with libass into that folder, or set `ffmpeg_path` in your config.

## Running

Always start the tool through a launcher in the project folder:

| Shell | Command |
|---|---|
| cmd / PowerShell | `.\vt.cmd ...` |
| PowerShell | `.\vt.ps1 ...` |
| bash | `./vt.sh ...` |

The launchers point these variables at folders inside the project before Python starts:

| Variable | Folder |
|---|---|
| `HF_HOME`, `HF_HUB_CACHE` | `models\hf` |
| `TORCH_HOME` | `models\torch` |
| `XDG_CACHE_HOME` | `.runtime\cache` |
| `PIP_CACHE_DIR` | `.runtime\pip-cache` |
| `TMP`, `TEMP` | `.runtime\tmp` |

Running `.venv\Scripts\python.exe -m video_transcribe ...` directly also works. The program sets the same variables itself on startup (`src/video_transcribe/paths.py`).

## Folder layout

```
video-transcribe/
├── config/default.yaml     default settings and subtitle style (edit a copy)
├── docs/                   documentation
├── fonts/                  subtitle fonts (put extra .ttf/.otf files here)
├── models/                 downloaded AI models (created on first use)
│   └── local/
│       ├── Systran--faster-whisper-small/         Whisper model
│       └── facebook--wav2vec2-base-960h/ ...       alignment models
├── output/                 results (default output folder)
├── src/video_transcribe/   source code
├── tests/                  unit and timing tests
├── .runtime/               uv, Python, ffmpeg, caches, temp files
├── .venv/                  Python virtual environment
├── setup.ps1 / setup.sh    installers
└── vt.cmd / vt.ps1 / vt.sh launchers
```

## Disk usage

| Item | Size |
|---|---|
| `.runtime` (Python, packages cache, ffmpeg) | ~1.3 GB |
| fonts | ~16 MB |
| Whisper `tiny` / `base` / `small` | 75 MB / 145 MB / 480 MB |
| Whisper `medium` | 1.5 GB |
| Whisper `large-v3` / `large-v3-turbo` | 3.1 GB / 1.6 GB |
| alignment model EN (`wav2vec2-base-960h`) | ~360 MB |
| alignment model ZH (`wav2vec2-large-xlsr-53-chinese-zh-cn`) | ~1.2 GB |

Models are downloaded only when first needed. A run on an English video never downloads the Chinese alignment model.

## How models are downloaded

Models are stored as plain folders in `models/local/<org>--<name>/`. Large files are downloaded in **100 MB pieces** (HTTP Range requests):

- each piece is retried on its own (`download.retries`, default 5), so a dropped connection costs at most one piece
- an interrupted download continues from the last finished piece the next time you run any command (the partial file is `<name>.part`)
- every finished file is checked against the SHA-256 published on Hugging Face
- a `.complete` marker in the folder means the model is ready. After that, no network access happens.

Change the piece size with `--chunk-mb` (e.g. `vt download-models --chunk-mb 50` on a poor connection) or `download.chunk_mb` in your config. You can also copy a `models/local/...` folder from another machine.

## Offline use

1. While online, run `.\vt.cmd download-models --model small` (or `medium`, etc.). This downloads the Whisper model and both alignment models.
2. Later, if you have no network at all, set `HF_HUB_OFFLINE=1` to skip the online update checks:

   ```powershell
   $env:HF_HUB_OFFLINE = "1"; .\vt.cmd run video.mp4
   ```

You can also copy the whole project folder, including `models\`, to another machine with the same OS and it works there as is.

## Updating

Package versions are pinned in `uv.lock`, so setup is reproducible. To move to the newest package versions, delete the lock file and the environment, then run setup again:

```powershell
Remove-Item uv.lock; Remove-Item -Recurse -Force .venv
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

## Uninstalling

Delete the project folder. Nothing was written anywhere else.
