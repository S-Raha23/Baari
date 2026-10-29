"""All Baari tunables in one place.

Defaults live in the dataclasses below. An optional YAML file (default `baari.yaml` in the
repo root) overrides any field, e.g.::

    prisma:
      model: prisma-v2.5
    commit_delay_ms: 150

The API key is never stored here; it is read from the `GNANI_API_KEY` environment variable
(loaded from `.env`).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
RAW_DIR = DATA_DIR / "raw"
USAGE_LOG = CACHE_DIR / "usage.jsonl"

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512  # Prisma requires exactly 512 samples (1,024 bytes) per frame
FRAME_BYTES = FRAME_SAMPLES * 2
FRAME_MS = 1000.0 * FRAME_SAMPLES / SAMPLE_RATE  # 32 ms at 16 kHz


@dataclass
class PrismaConfig:
    """Prisma streaming STT connection settings (see docs/API_NOTES.md)."""

    url: str = "wss://api.vachana.ai/stt/v3/stream"
    model: str = "prisma-v3.0"
    language_code: str = "hi-IN,en-IN"
    format: str = "codemix"
    sample_rate: int = SAMPLE_RATE
    vad_threshold: float = 0.7
    min_silence_ms: int = 500
    min_speech_ms: int = 100
    min_segment_ms: int = 120
    idle_timeout_sec: int = 60


@dataclass
class TimbreConfig:
    """Timbre TTS settings (see docs/API_NOTES.md)."""

    rest_url: str = "https://api.vachana.ai/api/v1/tts/inference"
    sse_url: str = "https://api.vachana.ai/api/v1/tts/sse"
    ws_url: str = "wss://api.vachana.ai/api/v1/tts"
    model: str = "timbre-v2.5"
    voice: str = "Poorvi"
    language: str = "hi-en"
    speed: float = 1.0
    sample_rate: int = SAMPLE_RATE


@dataclass
class BaariConfig:
    """Top-level configuration."""

    prisma: PrismaConfig = field(default_factory=PrismaConfig)
    timbre: TimbreConfig = field(default_factory=TimbreConfig)
    pause_min_ms: int = 150
    commit_delay_ms: int = 120
    tick_ms: int = 100
    t_max_ms: int = 2000
    fallback_min_silence_ms: int = 200
    api_call_confirm_threshold: int = 50


def _merge(obj: Any, overrides: dict[str, Any]) -> None:
    names = {f.name for f in fields(obj)}
    for key, value in overrides.items():
        if key not in names:
            raise KeyError(f"unknown config key: {key}")
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, dict):
            _merge(current, value)
        else:
            setattr(obj, key, type(current)(value) if current is not None else value)


def load_config(path: str | Path | None = None) -> BaariConfig:
    """Return defaults, overridden by the YAML file at `path` (or `baari.yaml` if present)."""
    cfg = BaariConfig()
    yaml_path = Path(path) if path else REPO_ROOT / "baari.yaml"
    if yaml_path.exists():
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        _merge(cfg, data)
    return cfg


def config_dict(cfg: Any) -> dict[str, Any]:
    """Plain-dict view of a config dataclass (for hashing and reports)."""
    return asdict(cfg)


def get_api_key() -> str:
    """Read GNANI_API_KEY from the environment / .env. Raises with instructions if missing."""
    load_dotenv(REPO_ROOT / ".env")
    key = os.environ.get("GNANI_API_KEY", "").strip()
    if not key or key == "your-gnani-api-key-here":
        raise RuntimeError(
            "GNANI_API_KEY is not set. Copy .env.example to .env and put your Gnani API key in it."
        )
    return key
