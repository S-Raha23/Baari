"""Disk cache for Timbre audio, keyed by hash(text + voice/model/language/speed/sample rate).

Prompts and agent replies are synthesised once and reused; re-running never spends credits.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from baari.audio.wavio import load_wav, save_wav
from baari.config import CACHE_DIR, TimbreConfig
from baari.tts.timbre import synth_rest
from baari.usage import stable_hash

TTS_CACHE = CACHE_DIR / "tts"


def tts_key(text: str, cfg: TimbreConfig) -> str:
    params = {k: v for k, v in asdict(cfg).items() if not k.endswith("_url")}
    return stable_hash(text, params)


def cached_path(text: str, cfg: TimbreConfig, root: Path = TTS_CACHE) -> Path:
    return root / f"{tts_key(text, cfg)}.wav"


def get_or_synth(text: str, cfg: TimbreConfig, api_key: str | None, root: Path = TTS_CACHE) -> np.ndarray:
    """int16 audio for `text`; calls Timbre REST only on a cache miss."""
    path = cached_path(text, cfg, root)
    if path.exists():
        return load_wav(path, cfg.sample_rate)
    if api_key is None:
        raise FileNotFoundError(f"TTS cache miss for {text!r} and no API key given")
    syn = synth_rest(text, cfg, api_key)
    pcm = np.frombuffer(syn.pcm, dtype="<i2")
    save_wav(path, pcm, cfg.sample_rate)
    meta = {"text": text, "voice": cfg.voice, "model": cfg.model, "language": cfg.language,
            "speed": cfg.speed, "sample_rate": cfg.sample_rate}
    path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return pcm
