# Configuration reference

All settings live in YAML. The defaults are in [`config/default.yaml`](../config/default.yaml), which has comments for every key. Don't edit that file. Make your own:

```powershell
vt init-config my.yaml        # full commented copy
vt run video.mp4 -c my.yaml
```

Your file is **deep-merged** over the defaults, so it only needs the keys you change:

```yaml
style:
  font_size: 64
```

Priority, from lowest to highest: `config/default.yaml` → your `--config` file → command-line options.

Typos are caught: an unknown key stops the run with a suggestion, for example `unknown config key 'style.font_szie' (did you mean 'font_size'?)`. Invalid values (a bad colour, an unknown position) are rejected too.

---

## `language`

| Key | Type | Default | Values |
|---|---|---|---|
| `language` | string | `auto` | `auto`, `en`, `zh` |

`auto` lets Whisper choose between English and Chinese only. Setting the language explicitly is slightly faster and avoids misdetection on videos that start with music.

---

## `transcription`

| Key | Type | Default | Description |
|---|---|---|---|
| `model` | string | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`, or any CTranslate2 Whisper model id from Hugging Face |
| `device` | string | `cpu` | `cpu`, `cuda`, `auto` (CUDA needs an NVIDIA GPU and a CUDA build of the libraries) |
| `compute_type` | string | `int8` | `int8` (fastest on CPU), `int8_float32`, `float32`, `float16` (GPU) |
| `beam_size` | int | `5` | higher values are slightly more accurate and slower. `1` = greedy. |
| `cpu_threads` | int | `0` | `0` = all cores |
| `vad` | bool | `true` | Silero voice activity detection: skips silence and music, which prevents invented text and timestamp drift there |
| `vad_min_silence_ms` | int | `500` | silence needed to split speech regions |
| `vad_speech_pad_ms` | int | `200` | audio kept around each detected speech region |
| `initial_prompt` | string/null | `null` | text that steers vocabulary and spelling, e.g. `"MacCMS, FFmpeg, Kubernetes"` |

---

## `alignment`

Forced alignment refines every word's timing against the audio. See [TIMING.md](TIMING.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | `false` (or `--no-align`) keeps Whisper's own word times |
| `min_score` | float 0–1 | `0.2` | if the aligner's average confidence for a segment is lower than this, that segment keeps Whisper's times |
| `models.en` | string | `facebook/wav2vec2-base-960h` | any Hugging Face wav2vec2 CTC model with a character vocabulary |
| `models.zh` | string | `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn` | the same, for Chinese characters |

---

## `chinese`

| Key | Type | Default | Values |
|---|---|---|---|
| `script` | string | `simplified` | `simplified`, `traditional`, `none` (keep whatever Whisper outputs) |

Whisper sometimes mixes Traditional characters into Mandarin output. OpenCC converts the text word by word, so word timings don't change. Alignment always runs on Simplified text, because that is the alignment model's vocabulary.

---

## `segmentation`

These settings control how words are grouped into on-screen cues, and how long each cue is shown. All times are in seconds.

| Key | Type | Default | Description |
|---|---|---|---|
| `max_chars.en` | int | `42` | max characters per line for English (42 is a common broadcast standard) |
| `max_chars.zh` | int | `18` | max full-width characters per line for Chinese. Latin letters and digits count as ½. |
| `max_lines` | int | `2` | lines per cue |
| `max_duration` | float | `6.0` | a cue is never shown longer than this |
| `min_duration` | float | `0.8` | short cues are extended to this length, **but only into silence**, never over the next cue |
| `min_gap` | float | `0.08` | minimum blank time between two cues, so players don't merge them |
| `pause_split` | float | `0.6` | a pause in speech at least this long always starts a new cue |
| `lead_in` | float | `0.05` | the cue appears this long before the first word |
| `end_padding` | float or `{en, zh}` | `{en: 0.15, zh: 0.3}` | the cue stays this long after the last word. Chinese is longer because the aligner marks where the final syllable *begins*. A single number applies to both languages. |
| `time_offset` | float | `0.0` | constant shift of all cues. Normally keep it at 0, because container offsets are fixed automatically. |

Cues also split at sentence ends (`. ? ! 。 ？ ！`). When text has to be broken for length, the tool prefers a comma (`, ， 、`). Lines inside a cue are balanced so they have about the same length.

---

## `style`

This sets the look of burned-in subtitles and of the `.ass` file. Pixel values are written **for a 1080p video** and scaled to the actual video height. `font_size: 52` gives 52 px at 1080p, 35 px at 720p and 104 px at 4K, so the subtitles look the same at any resolution.

| Key | Type | Default | Description |
|---|---|---|---|
| `font_name` | string | `Noto Sans SC` | font family name. It must be in `fonts/` or installed on the system. |
| `font_size` | number | `52` | text height in px (at 1080p) |
| `bold` | bool | `false` | |
| `italic` | bool | `false` | |
| `primary_color` | colour | `#FFFFFF` | text colour |
| `outline_color` | colour | `#000000` | outline colour (with `border_style: outline`) |
| `back_color` | colour | `#A0000000` | shadow colour, and the **box colour** with `border_style: box` |
| `border_style` | string | `outline` | `outline` = outlined text with a drop shadow. `box` = opaque rectangle behind the text. |
| `outline` | number | `2.5` | outline width in px. With `box`, the padding around the text. |
| `shadow` | number | `1.0` | shadow offset in px (`0` = none) |
| `spacing` | number | `0` | extra space between letters, in px |
| `position` | string | `bottom-center` | see [Positions](#positions) |
| `margin_v` | int | `60` | distance from the bottom edge (bottom positions) or the top edge (top positions), in px |
| `margin_l` | int | `40` | left margin, in px |
| `margin_r` | int | `40` | right margin, in px |
| `overrides.en` | mapping | `{}` | any style keys above, applied only to English videos |
| `overrides.zh` | mapping | `{font_size: 56}` | any style keys above, applied only to Chinese videos |

### Colours

Colours are written as `"#RRGGBB"` (opaque) or `"#AARRGGBB"`, where `AA` is the **opacity**: `FF` = solid, `80` ≈ 50 %, `00` = invisible. Always put quotes around colours in YAML, because `#` starts a comment.

| Example | Meaning |
|---|---|
| `"#FFFFFF"` | white |
| `"#FFE600"` | yellow |
| `"#000000"` | black |
| `"#A0000000"` | black at ~63 % opacity |
| `"#00000000"` | fully transparent |

### Positions

```
top-left       top-center       top-right
middle-left    middle-center    middle-right
bottom-left    bottom-center    bottom-right
```

### Fonts

The `fonts/` folder is given to the subtitle renderer, so any `.ttf` or `.otf` you copy there can be used by its **family name** (the name shown in the font preview, not the file name). The bundled Noto Sans SC covers Chinese and Latin. If you choose a Latin-only font for Chinese videos, the characters show up as boxes. Use a CJK font for `overrides.zh`:

```yaml
style:
  font_name: Arial                  # English videos
  overrides:
    zh: {font_name: Noto Sans SC}   # Chinese videos
```

### Style recipes

**Yellow text, thick outline (classic movie style)**

```yaml
style:
  primary_color: "#FFE600"
  outline_color: "#000000"
  outline: 3.5
  shadow: 0
```

**Semi-transparent box (good on busy backgrounds)**

```yaml
style:
  border_style: box
  back_color: "#B0000000"
  outline: 8          # padding around the text
  shadow: 0
```

**Top of the screen, smaller**

```yaml
style:
  position: top-center
  margin_v: 40
  font_size: 44
```

**Large text for mobile / vertical video**

```yaml
style:
  font_size: 72
  bold: true
  margin_v: 220
segmentation:
  max_chars: {en: 28, zh: 12}
```

---

## `output`

| Key | Type | Default | Description |
|---|---|---|---|
| `mode` | string | `burn` | `burn`, `soft`, `none` (see [USAGE.md](USAGE.md#what-burn-and-soft-mean)) |
| `formats` | list | `[srt, ass]` | subtitle files to write: `srt`, `ass`, `vtt` |
| `dir` | path | `output` | output folder. A relative path is resolved against the project folder. |
| `suffix` | string | `_subtitled` | added to the video file name |
| `overwrite` | bool | `false` | replace existing outputs |
| `keep_work_files` | bool | `false` | keep `audio.wav` + `transcript.json` in `<dir>/<name>_work/` |

---

## `encoding`

Used only in `burn` mode, because burning in requires re-encoding the video. Audio is always copied unchanged.

| Key | Default | Description |
|---|---|---|
| `mp4.video_codec` | `libx264` | H.264 |
| `mp4.crf` | `18` | quality: 0 = lossless, 18 ≈ visually lossless, 23 = x264 default, higher = smaller file |
| `mp4.preset` | `medium` | `ultrafast` … `veryslow`. Slower gives a smaller file at the same quality. |
| `mp4.pix_fmt` | `yuv420p` | `null` keeps the source pixel format |
| `webm.video_codec` | `libvpx-vp9` | VP9 |
| `webm.crf` | `32` | VP9 quality (0–63, lower = better) |
| `webm.cpu_used` | `4` | 0 (slowest, best) … 8 (fastest) |
| `webm.pix_fmt` | `yuv420p` | |

---

## `ffmpeg_path`

| Key | Default | Description |
|---|---|---|
| `ffmpeg_path` | `null` | folder that contains `ffmpeg` and `ffprobe` (or the path to `ffmpeg` itself). `null` uses the bundled `.runtime/ffmpeg/bin`. ffmpeg must be built with libass for burn mode. |

---

## `download`

| Key | Default | Description |
|---|---|---|
| `chunk_mb` | `100` | models are downloaded in pieces of this many MB (HTTP Range requests). Each piece is retried on its own, and downloads resume after an interruption. |
| `retries` | `5` | attempts per piece before giving up (run again to resume) |
