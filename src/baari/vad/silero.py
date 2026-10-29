"""Local VAD lane: Silero VAD (ONNX Runtime, CPU) + a hysteresis pause tracker.

`SileroVAD.prob(frame)` gives a speech probability per 512-sample frame (32 ms).
`PauseTracker` turns probabilities into events on the shared timeline:

- `speech_start`: speech confirmed (onset back-dated to the first speech frame);
- `silence_start`: provisional, after `silence_min_ms` of silence (fast pause-onset signal);
- `silence_cancel`: speech resumed before the silence became a pause;
- `pause_start`: silence has lasted `pause_min_ms`; onset back-dated to the speech offset.

Decisions at frame k use only frames <= k, so the same code runs live and offline.
"""

from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort

from baari.config import FRAME_MS, FRAME_SAMPLES, REPO_ROOT, SAMPLE_RATE

MODEL_URL = "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx"
MODEL_SHA256 = "2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f"
MODEL_PATH = REPO_ROOT / "models" / "silero_vad.onnx"
CONTEXT = 64  # samples of left context the v5 model expects at 16 kHz


def ensure_model(path: Path = MODEL_PATH) -> Path:
    """Download Silero VAD v5.1.2 (MIT licence) once and verify its SHA-256."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        raise RuntimeError(f"{path} has unexpected SHA-256 {digest}; delete it and retry")
    return path


class SileroVAD:
    """Stateful frame-by-frame Silero VAD. Call `reset()` between independent streams."""

    def __init__(self, path: Path | None = None) -> None:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(ensure_model(path or MODEL_PATH)), sess_options=opts,
                                            providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        """Speech probability for one 512-sample int16 (or float) frame."""
        x = frame.astype(np.float32)
        if frame.dtype == np.int16:
            x /= 32768.0
        assert len(x) == FRAME_SAMPLES, f"expected {FRAME_SAMPLES} samples, got {len(x)}"
        inp = np.concatenate([self._context, x])[None, :]
        out, self._state = self.session.run(None, {"input": inp, "state": self._state, "sr": self._sr})
        self._context = x[-CONTEXT:]
        return float(out[0, 0])


@dataclass
class VadEvent:
    """A local-lane event. `onset_ms` is in audio time; `detected_ms` is when it was known."""

    kind: str  # "speech_start" | "silence_start" | "silence_cancel" | "pause_start"
    onset_ms: float
    detected_ms: float
    t_ns: int = 0  # shared-clock time of the frame that triggered detection
    segment_start_ms: float | None = None  # for pause_start: start of the segment that ended


class PauseTracker:
    """Hysteresis over per-frame speech probabilities.

    Speech opens when p >= `on` for `min_speech_ms`; a frame counts as silence when p < `off`.
    A pause starts once silence lasts `pause_min_ms`. Between `off` and `on` the current state
    is kept, which removes flicker.
    """

    def __init__(self, *, on: float = 0.5, off: float = 0.35, min_speech_ms: float = 64.0,
                 pause_min_ms: float = 150.0, silence_min_ms: float = 64.0) -> None:
        self.on, self.off = on, off
        self.need_on = max(1, int(np.ceil(min_speech_ms / FRAME_MS)))
        self.need_off = max(1, int(np.ceil(pause_min_ms / FRAME_MS)))
        self.need_sil = min(self.need_off, max(1, int(np.ceil(silence_min_ms / FRAME_MS))))
        self.reset()

    def reset(self) -> None:
        self.k = 0
        self.in_speech = False
        self.run_on = self.run_off = 0
        self.seg_start = 0

    def update(self, p: float, t_ns: int = 0) -> list[VadEvent]:
        """Feed one frame's probability; return any events it completes."""
        k = self.k
        self.k += 1
        now_ms = (k + 1) * FRAME_MS  # the frame is complete at its end
        events: list[VadEvent] = []
        if not self.in_speech:
            self.run_on = self.run_on + 1 if p >= self.on else 0
            if self.run_on >= self.need_on:
                self.in_speech, self.run_off = True, 0
                self.seg_start = k - self.need_on + 1
                events.append(VadEvent("speech_start", self.seg_start * FRAME_MS, now_ms, t_ns))
        else:
            if p < self.off:
                self.run_off += 1
            elif p >= self.on:
                if self.run_off >= self.need_sil:
                    end = k - self.run_off
                    events.append(VadEvent("silence_cancel", end * FRAME_MS, now_ms, t_ns))
                self.run_off = 0
            if self.run_off == self.need_sil and self.need_sil < self.need_off:
                end = k - self.need_sil + 1
                events.append(VadEvent("silence_start", end * FRAME_MS, now_ms, t_ns,
                                       segment_start_ms=self.seg_start * FRAME_MS))
            if self.run_off >= self.need_off:
                end = k - self.need_off + 1
                events.append(VadEvent("pause_start", end * FRAME_MS, now_ms, t_ns,
                                       segment_start_ms=self.seg_start * FRAME_MS))
                self.in_speech, self.run_on = False, 0
        return events


def run_vad(pcm: np.ndarray, vad: SileroVAD | None = None,
            tracker: PauseTracker | None = None) -> tuple[np.ndarray, list[VadEvent]]:
    """Offline pass over a clip: per-frame probabilities and events."""
    vad = vad or SileroVAD()
    tracker = tracker or PauseTracker()
    vad.reset()
    tracker.reset()
    n = len(pcm) // FRAME_SAMPLES
    probs = np.zeros(n, dtype=np.float32)
    events: list[VadEvent] = []
    for k in range(n):
        probs[k] = vad.prob(pcm[k * FRAME_SAMPLES:(k + 1) * FRAME_SAMPLES])
        events.extend(tracker.update(float(probs[k])))
    return probs, events
