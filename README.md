# video-transcribe

Offline command-line tool that turns speech in a video into **accurately timed, styled subtitles**.

- **Languages:** English (`en`) and Chinese (`zh`, output in Simplified by default), auto-detected
- **Videos:** MP4 and WEBM
- **Pipeline:** extract audio → transcribe (Whisper) → refine word timing (wav2vec2 forced alignment) → build subtitle cues → burn into the video or add as a track
- **Style:** fonts, colours, outline, box, position and margins set in a YAML file (`config/default.yaml`)
- **Free and offline:** open-source models run locally on your CPU. No API keys, accounts or cloud services.
- **Self-contained:** Python, packages, ffmpeg, fonts, models and caches all live **inside this folder**. Nothing is installed system-wide.

## Quick start (Windows)

```powershell
cd video-transcribe
powershell -ExecutionPolicy Bypass -File .\setup.ps1      # one-time, ~1.5 GB download
.\vt.cmd doctor                                            # check the installation
.\vt.cmd run C:\videos\talk.mp4                            # -> output\talk_subtitled.mp4
```

Linux / macOS: `./setup.sh`, then `./vt.sh run video.mp4`.

The first run downloads the Whisper model (~480 MB for `small`) and the alignment model (~360 MB EN, ~1.2 GB ZH) into `models/`. Later runs work fully offline.

## Common commands

```powershell
.\vt.cmd run talk.mp4                      # auto language, burn subtitles in
.\vt.cmd run talk.webm --lang zh           # Chinese
.\vt.cmd run talk.mp4 --mode soft          # add a selectable subtitle track (no re-encode)
.\vt.cmd transcribe talk.mp4 -f srt,vtt    # subtitle files only
.\vt.cmd run D:\videos\ -m medium          # every MP4/WEBM in a folder, bigger model
.\vt.cmd init-config my.yaml               # copy the default style/config to edit
.\vt.cmd run talk.mp4 -c my.yaml           # use your style
.\vt.cmd burn talk.mp4 -s output\talk.en.srt -c my.yaml --overwrite   # re-style / hand-edited subs
```

Outputs go to `output/`:

| File | What it is |
|---|---|
| `talk_subtitled.mp4` | video with subtitles (burned in, or as a soft track) |
| `talk.en.srt` | plain subtitles, for editing or for players |
| `talk.en.ass` | styled subtitles (same style as the burned-in ones) |

## Changing the subtitle style

Make a YAML file that holds only the keys you want to change:

```yaml
# my.yaml
style:
  font_size: 60
  primary_color: "#FFE600"     # yellow text
  border_style: box            # dark box behind the text
  back_color: "#B0000000"
  position: bottom-center
  margin_v: 80
```

```powershell
.\vt.cmd run talk.mp4 -c my.yaml
```

Every option is described in [docs/CONFIG.md](docs/CONFIG.md).

## Documentation

| Doc | Contents |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | setup, folder layout, offline use, disk usage, uninstalling |
| [docs/USAGE.md](docs/USAGE.md) | full CLI reference with examples |
| [docs/CONFIG.md](docs/CONFIG.md) | every YAML option, colours, positions, style recipes |
| [docs/TIMING.md](docs/TIMING.md) | how subtitle timing is kept accurate, tuning, measured accuracy |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | modules, data flow, intermediate formats |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | common problems and fixes |

## Open-source components

| Component | Licence | Used for |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / OpenAI Whisper models | MIT | speech recognition |
| [Silero VAD](https://github.com/snakers4/silero-vad) (bundled in faster-whisper) | MIT | speech/silence detection |
| [wav2vec2-base-960h](https://huggingface.co/facebook/wav2vec2-base-960h) | Apache-2.0 | English forced alignment |
| [wav2vec2-large-xlsr-53-chinese-zh-cn](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn) | Apache-2.0 | Chinese forced alignment |
| [PyTorch](https://pytorch.org), [transformers](https://github.com/huggingface/transformers) | BSD / Apache-2.0 | running wav2vec2 |
| [OpenCC](https://github.com/yichen0831/opencc-python) | Apache-2.0 | Traditional ↔ Simplified Chinese |
| [FFmpeg](https://ffmpeg.org) + libass (gyan.dev build) | GPL | audio extraction, subtitle rendering, encoding |
| [Noto Sans SC](https://github.com/notofonts/noto-cjk) | SIL OFL 1.1 | subtitle font (Chinese + Latin) |
| [uv](https://github.com/astral-sh/uv) | MIT / Apache-2.0 | Python and package management |
