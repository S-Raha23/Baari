"""WAV / PCM helpers: load, save, resample to 16 kHz mono int16, split into Prisma frames."""

from __future__ import annotations

import io
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from baari.config import FRAME_BYTES, FRAME_SAMPLES, SAMPLE_RATE


def to_int16(x: np.ndarray) -> np.ndarray:
    """Float [-1, 1] or int16 array -> int16 mono."""
    if x.ndim > 1:
        x = x.mean(axis=1)
    if x.dtype == np.int16:
        return x
    return np.clip(np.round(x * 32767.0), -32768, 32767).astype(np.int16)


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Polyphase resampling of a float array."""
    if sr_in == sr_out:
        return x
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g)


def load_wav(path: str | Path | bytes, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Load any soundfile-readable audio (path or bytes) as int16 mono at `sr`."""
    src = io.BytesIO(path) if isinstance(path, bytes) else str(path)
    data, sr_in = sf.read(src, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return to_int16(resample(data, sr_in, sr))


def save_wav(path: str | Path, x: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    """Write int16 mono audio."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), to_int16(x), sr, subtype="PCM_16")


def silence(ms: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """int16 zeros of the given duration."""
    return np.zeros(int(round(sr * ms / 1000.0)), dtype=np.int16)


def frames(pcm: np.ndarray) -> list[bytes]:
    """Split int16 audio into exact 1,024-byte frames, zero-padding the last one."""
    pcm = to_int16(pcm)
    n = int(np.ceil(len(pcm) / FRAME_SAMPLES)) if len(pcm) else 0
    padded = np.zeros(n * FRAME_SAMPLES, dtype="<i2")
    padded[: len(pcm)] = pcm
    raw = padded.tobytes()
    out = [raw[i : i + FRAME_BYTES] for i in range(0, len(raw), FRAME_BYTES)]
    assert all(len(f) == FRAME_BYTES for f in out)
    return out
