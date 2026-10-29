"""Configuration: defaults (config/default.yaml) <- user YAML <- CLI flags."""

from __future__ import annotations

import copy
import difflib
import re
from pathlib import Path
from typing import Any

import yaml

from . import paths


class ConfigError(ValueError):
    pass


# Keys whose values are free-form mappings (not validated key-by-key against defaults).
_FREE_MAPS = {("alignment", "models")}

_CHOICES = {
    ("language",): {"auto", "en", "zh"},
    ("transcription", "device"): {"cpu", "cuda", "auto"},
    ("chinese", "script"): {"simplified", "traditional", "none"},
    ("style", "border_style"): {"outline", "box"},
    ("style", "position"): {
        f"{v}-{h}" for v in ("top", "middle", "bottom") for h in ("left", "center", "right")
    },
    ("output", "mode"): {"burn", "soft", "none"},
}

_COLOR_RE = re.compile(r"^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
SUBTITLE_FORMATS = {"srt", "ass", "vtt"}
LANGUAGES = ("en", "zh")


def load_yaml(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return data


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _check_keys(user: dict, ref: dict, trail: tuple = ()) -> None:
    for key, value in user.items():
        here = trail + (key,)
        if here in _FREE_MAPS:
            continue
        if trail == ("style", "overrides"):
            if key not in LANGUAGES:
                raise ConfigError(f"style.overrides.{key}: language must be one of {LANGUAGES}")
            if value:
                _check_keys(value, _STYLE_REF, here)
            continue
        if key not in ref:
            hint = difflib.get_close_matches(str(key), [str(k) for k in ref], n=1)
            msg = f"unknown config key '{'.'.join(map(str, here))}'"
            if hint:
                msg += f" (did you mean '{hint[0]}'?)"
            raise ConfigError(msg)
        if isinstance(value, dict) and isinstance(ref[key], dict):
            _check_keys(value, ref[key], here)


_STYLE_REF: dict = {}


def _get(cfg: dict, trail: tuple) -> Any:
    cur: Any = cfg
    for k in trail:
        cur = cur[k]
    return cur


def validate(cfg: dict) -> None:
    for trail, choices in _CHOICES.items():
        value = _get(cfg, trail)
        if value not in choices:
            raise ConfigError(
                f"{'.'.join(trail)}: '{value}' is not one of {sorted(choices)}"
            )
    styles = [cfg["style"]] + [o for o in (cfg["style"].get("overrides") or {}).values() if o]
    for st in styles:
        for key in ("primary_color", "outline_color", "back_color"):
            if key in st and not _COLOR_RE.match(str(st[key])):
                raise ConfigError(f"style.{key}: '{st[key]}' must be #RRGGBB or #AARRGGBB")
        if "position" in st and st["position"] not in _CHOICES[("style", "position")]:
            raise ConfigError(f"style.position: invalid value '{st['position']}'")
    fmts = cfg["output"]["formats"]
    if isinstance(fmts, str):
        fmts = cfg["output"]["formats"] = [f.strip() for f in fmts.split(",") if f.strip()]
    bad = set(fmts) - SUBTITLE_FORMATS
    if bad:
        raise ConfigError(f"output.formats: unknown format(s) {sorted(bad)}")
    seg = cfg["segmentation"]
    for key in ("max_duration", "min_duration", "min_gap", "pause_split", "lead_in", "end_padding"):
        values = seg[key].values() if isinstance(seg[key], dict) else [seg[key]]
        if any(float(v) < 0 for v in values):
            raise ConfigError(f"segmentation.{key} must be >= 0")
    if seg["min_duration"] > seg["max_duration"]:
        raise ConfigError("segmentation.min_duration must be <= max_duration")
    if int(seg["max_lines"]) < 1:
        raise ConfigError("segmentation.max_lines must be >= 1")
    for lang in LANGUAGES:
        if int(seg["max_chars"].get(lang, 0)) < 4:
            raise ConfigError(f"segmentation.max_chars.{lang} must be >= 4")
    if not 0 <= float(cfg["alignment"]["min_score"]) <= 1:
        raise ConfigError("alignment.min_score must be between 0 and 1")


def load_config(user_path: str | Path | None = None, cli_overrides: dict | None = None) -> dict:
    """Return the merged, validated configuration."""
    global _STYLE_REF
    defaults = load_yaml(paths.DEFAULT_CONFIG)
    _STYLE_REF = {k: v for k, v in defaults["style"].items() if k != "overrides"}
    cfg = defaults
    if user_path:
        user = load_yaml(user_path)
        _check_keys(user, defaults)
        cfg = deep_merge(cfg, user)
    if cli_overrides:
        cfg = deep_merge(cfg, cli_overrides)
    validate(cfg)
    return cfg


def per_language(value, language: str):
    """A setting that is either one value or a mapping {en: ..., zh: ...}."""
    if isinstance(value, dict):
        return value.get(language, next(iter(value.values())))
    return value


def style_for(cfg: dict, language: str) -> dict:
    """Base style merged with the per-language override."""
    base = {k: v for k, v in cfg["style"].items() if k != "overrides"}
    override = (cfg["style"].get("overrides") or {}).get(language) or {}
    return deep_merge(base, override)
