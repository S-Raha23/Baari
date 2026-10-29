"""Session recorder: one continuous mic WAV + per-block clock stamps + an event log.

Everything that happens in a session (card shown, bot prompt played, Done pressed) is logged
with a shared-clock timestamp. At the end, a least-squares fit of block timestamps against
sample counts maps any clock time to a sample position in `mic.wav`, which is how labels
line up with the audio.

Files written to data/raw/<speaker>/<session>/:
    mic.wav       16 kHz mono int16, the whole session
    blocks.npy    (n, 2) int64: block index, t_ns when delivered
    events.jsonl  one JSON object per event (t_ns, type, ...), flushed as it happens
    session.json  metadata (written at start, completed at the end)
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from baari.audio.capture import MicCapture
from baari.clock import now_ns
from baari.config import FRAME_SAMPLES, SAMPLE_RATE


def fit_clock(blocks: np.ndarray) -> tuple[float, float]:
    """Return (a, b) with sample ≈ a * t_ns + b, fitted on block delivery times.

    Block k is delivered when its last sample has been captured, i.e. at sample (k+1)*512.
    """
    k = blocks[:, 0].astype(np.float64)
    t = blocks[:, 1].astype(np.float64)
    samples = (k + 1) * FRAME_SAMPLES
    t0 = t[0]
    a, b0 = np.polyfit(t - t0, samples, 1)
    return float(a), float(b0 - a * t0)


def t_to_sample(t_ns: int | float, fit: tuple[float, float]) -> int:
    a, b = fit
    return int(round(a * float(t_ns) + b))


class SessionRecorder:
    """Records the mic to disk in a background thread while the session UI runs."""

    def __init__(self, session_dir: Path, meta: dict[str, Any], device: int | None = None) -> None:
        self.dir = session_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = dict(meta)
        self.device = device
        self._events = (self.dir / "events.jsonl").open("a", encoding="utf-8")
        self._blocks: list[tuple[int, int]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mic: MicCapture | None = None
        self._wav: sf.SoundFile | None = None
        self.peak = 0  # running peak level, for a clipping warning

    def _write_meta(self) -> None:
        (self.dir / "session.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=1),
                                               encoding="utf-8")

    def event(self, kind: str, **fields: Any) -> int:
        """Log an event now; returns its timestamp."""
        t = now_ns()
        self._events.write(json.dumps({"t_ns": t, "type": kind, **fields}, ensure_ascii=False) + "\n")
        self._events.flush()
        return t

    def _run(self) -> None:
        assert self._mic and self._wav
        while not self._stop.is_set() or not self._mic.queue.empty():
            try:
                block = self._mic.read(timeout=0.2)
            except Exception:  # queue.Empty
                continue
            self._wav.write(block.pcm)
            self._blocks.append((block.index, block.t_ns))
            self.peak = max(self.peak, int(np.abs(block.pcm.astype(np.int32)).max()))

    def __enter__(self) -> "SessionRecorder":
        self.meta["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self._write_meta()
        self._wav = sf.SoundFile(str(self.dir / "mic.wav"), "w", samplerate=SAMPLE_RATE, channels=1,
                                 subtype="PCM_16")
        self._mic = MicCapture(device=self.device).__enter__()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.event("recording_start")
        return self

    def __exit__(self, *exc: object) -> None:
        self.event("recording_end")
        assert self._mic and self._thread and self._wav
        self._mic.__exit__()
        self._stop.set()
        self._thread.join(timeout=5)
        self._wav.close()
        self._events.close()
        blocks = np.array(self._blocks, dtype=np.int64).reshape(-1, 2)
        np.save(self.dir / "blocks.npy", blocks)
        self.meta["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.meta["duration_s"] = round(len(blocks) * FRAME_SAMPLES / SAMPLE_RATE, 2)
        self.meta["input_overflows"] = self._mic.overflows
        self.meta["peak_level"] = self.peak
        if len(blocks) >= 2:
            a, b = fit_clock(blocks)
            self.meta["clock_fit"] = {"a_samples_per_ns": a, "b_samples": b,
                                      "rate_hz_measured": round(a * 1e9, 2)}
        self.meta["complete"] = exc[0] is None
        self._write_meta()
