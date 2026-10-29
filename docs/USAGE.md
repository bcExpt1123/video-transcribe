# Usage

```
vt <command> [options]
```

Run commands through a launcher in the project folder: `.\vt.cmd` (Windows), `./vt.sh` (bash). The examples below use `vt` for short.

| Command | Purpose |
|---|---|
| [`run`](#vt-run) | full pipeline: audio → transcript → subtitles → video |
| [`transcribe`](#vt-transcribe) | the same, but writes only subtitle files |
| [`burn`](#vt-burn) | add an existing `.srt` / `.vtt` / `.ass` file to a video |
| [`init-config`](#vt-init-config) | copy the default YAML so you can edit it |
| [`download-models`](#vt-download-models) | pre-download models for offline use |
| [`doctor`](#vt-doctor) | check the installation |

---

## `vt run`

```
vt run INPUT [INPUT ...] [options]
```

`INPUT` is one or more `.mp4` / `.webm` files or folders. For a folder, every MP4/WEBM file directly inside it is processed. Models are loaded once and reused for the whole batch.

| Option | Default | Description |
|---|---|---|
| `-l, --lang {auto,en,zh}` | `auto` | spoken language. `auto` picks English or Chinese. |
| `--mode {burn,soft,none}` | `burn` | `burn` draws the subtitles into the picture. `soft` adds a selectable subtitle track. `none` writes subtitle files only. |
| `-m, --model NAME` | `small` | Whisper model: `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo` |
| `--no-align` | off | skip wav2vec2 forced alignment (faster, less precise timing) |
| `-f, --formats LIST` | `srt,ass` | subtitle files to write: any of `srt`, `ass`, `vtt` |
| `--offset SECONDS` | `0` | shift every subtitle (`0.2` = later, `-0.2` = earlier) |
| `-c, --config FILE` | – | your YAML config, merged over `config/default.yaml` |
| `-o, --output DIR` | `output/` | output folder |
| `--overwrite` | off | replace existing output files (without it the tool stops rather than overwrite) |
| `--keep-work` | off | keep `audio.wav` and `transcript.json` in `output/<name>_work/` |
| `-v, --verbose` | – | debug output, including the ffmpeg commands that run |
| `-q, --quiet` | – | only warnings and errors |

Command-line options take priority over the YAML config.

### Outputs

For an input `talk.mp4` whose speech is English:

| File | Created when |
|---|---|
| `output/talk_subtitled.mp4` | mode `burn` or `soft` (same container as the input) |
| `output/talk.en.srt` | `srt` in formats |
| `output/talk.en.ass` | `ass` in formats (styled, like the burned-in subtitles) |
| `output/talk.en.vtt` | `vtt` in formats |

The language code (`en` / `zh`) in the file name lets most players pick up the subtitle file automatically.

### Examples

```powershell
# English video, defaults: burned-in subtitles
vt run lecture.mp4

# Chinese WEBM with the more accurate medium model
vt run vlog.webm --lang zh --model medium

# Whole folder, soft subtitles, into another folder
vt run D:\videos --mode soft -o D:\videos\subtitled

# Your own style
vt run lecture.mp4 -c styles\yellow-box.yaml

# Everything subtitles ever need: srt + ass + vtt, keep intermediates for inspection
vt run lecture.mp4 -f srt,ass,vtt --keep-work -v
```

### What `burn` and `soft` mean

| | `burn` (default) | `soft` |
|---|---|---|
| Style from YAML | always shown exactly | ignored by most players |
| Can be switched off by the viewer | no | yes |
| Re-encodes the video | yes (slower; quality set by `encoding`) | no (fast, lossless) |
| MP4 subtitle codec | – | `mov_text` |
| WEBM subtitle codec | – | `webvtt` |

The audio track is always copied unchanged.

---

## `vt transcribe`

```
vt transcribe INPUT [INPUT ...] [options]
```

The same as `vt run --mode none`: writes subtitle files only and leaves the video untouched. It takes the same options as `run`, except `--mode`.

```powershell
vt transcribe interview.mp4 -f srt
```

---

## `vt burn`

```
vt burn VIDEO -s SUBTITLE [options]
```

Adds an **existing** subtitle file to a video. Typical uses:

- **Restyle without transcribing again:** change your YAML, then burn the `.srt` from an earlier run.
- **Hand-corrected text:** fix words in the `.srt` with a text editor, then burn it.
- **Subtitles from elsewhere.**

| Option | Description |
|---|---|
| `-s, --subs FILE` | `.srt` or `.vtt` (styled from the YAML) or `.ass` (used exactly as is) |
| `-l, --lang {auto,en,zh}` | which `style.overrides` entry to apply (default: guessed from the text) |
| `--soft` | add as a soft track instead of burning in (`.srt` / `.vtt` only) |
| `--offset SECONDS` | shift the subtitles (`.srt` / `.vtt` only) |
| `-c, --config FILE` | style / encoding config |
| `-o, --output PATH` | output folder, **or** a full file name ending in `.mp4` / `.webm` |
| `--overwrite` | replace an existing output |

```powershell
vt run talk.mp4 --mode none                    # 1. subtitles only
notepad output\talk.en.srt                     # 2. fix a few words
vt burn talk.mp4 -s output\talk.en.srt -c my.yaml -o output\talk_final.mp4
```

---

## `vt init-config`

```
vt init-config [PATH] [--overwrite]
```

Copies `config/default.yaml` (all options, with comments) to `PATH` (default `my-config.yaml`). Edit the copy and pass it with `-c`. You can delete every key you don't change. See [CONFIG.md](CONFIG.md).

---

## `vt download-models`

```
vt download-models [-m MODEL] [-l {en,zh}] [--no-align] [--chunk-mb N] [-c CONFIG]
```

Downloads the Whisper model (default: the one in your config) and the alignment models (both languages unless `-l` is given) into `models/local/`. Large files come in 100 MB pieces (`--chunk-mb` to change), each retried separately. If it stops, run it again and it resumes. Files are SHA-256 verified. Run it while online if you'll be working offline later.

```powershell
vt download-models -m medium
vt download-models -m large-v3 -l zh
```

---

## `vt doctor`

Checks the installation and prints one line per item: Python, ffmpeg/ffprobe, libass support, fonts, cache folder locations (each must be inside the project), installed package versions and config validity. It exits with code 1 if anything is wrong.

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | one or more inputs failed (missing file, unsupported format, ffmpeg error, output exists) |
| 2 | config error (unknown key, invalid value) |
| 130 | interrupted with Ctrl+C |

## Choosing a model

| Model | Speed on a 6-core CPU* | Notes |
|---|---|---|
| `tiny`, `base` | very fast | rough text, fine for tests |
| `small` (default) | ~3–5× real time | good English, decent Chinese |
| `medium` | ~1–2× real time | recommended for Chinese |
| `large-v3-turbo` | ~1–2× real time | close to large-v3 quality |
| `large-v3` | slower than real time | best text quality |

\* "3× real time" means a 10-minute video takes about 3 minutes. Forced alignment adds about 10–30 % on top. Burn-in encoding time depends on the resolution and `encoding.preset`.

The model choice affects the **text** quality. **Timing** precision comes mostly from forced alignment and is similar across models.
