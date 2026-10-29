"""Bot-voice playback with position tracking, ducking and stop.

A `Player` plays one utterance made of text chunks (usually sentences synthesised separately),
so at any moment it knows which chunk is playing and how much of the text the caller has heard
(`heard_text`, needed for barge-in). Volume changes ramp over 5 ms to avoid clicks.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd

from baari.clock import now_ns
from baari.config import SAMPLE_RATE

RAMP_SAMPLES = SAMPLE_RATE * 5 // 1000


def ramp(gain: float, target: float, n: int) -> np.ndarray:
    """Per-sample gains moving from `gain` to `target` at a full-scale rate of RAMP_SAMPLES."""
    step = 1.0 / RAMP_SAMPLES
    k = np.arange(1, n + 1, dtype=np.float32)
    if target >= gain:
        return np.minimum(gain + step * k, target).astype(np.float32)
    return np.maximum(gain - step * k, target).astype(np.float32)


@dataclass
class Utterance:
    """Concatenated PCM plus the sample offset where each text chunk starts."""

    pcm: np.ndarray  # int16
    texts: list[str]
    starts: list[int]  # sample offset of each chunk

    @classmethod
    def from_chunks(cls, chunks: list[tuple[str, np.ndarray]], gap_ms: float = 150.0) -> "Utterance":
        gap = np.zeros(int(SAMPLE_RATE * gap_ms / 1000), dtype=np.int16)
        parts, texts, starts, pos = [], [], [], 0
        for i, (text, pcm) in enumerate(chunks):
            if i:
                parts.append(gap)
                pos += len(gap)
            texts.append(text)
            starts.append(pos)
            parts.append(pcm.astype(np.int16))
            pos += len(pcm)
        return cls(np.concatenate(parts) if parts else np.zeros(0, np.int16), texts, starts)

    def chunk_at(self, sample: int) -> int:
        """Index of the chunk playing at `sample` (-1 before the start)."""
        return int(np.searchsorted(self.starts, sample, side="right")) - 1


@dataclass
class PlaybackLog:
    """Shared-clock timestamps of playback milestones."""

    start_ns: int | None = None
    end_ns: int | None = None
    stopped_ns: int | None = None
    duck_ns: list[int] = field(default_factory=list)
    restore_ns: list[int] = field(default_factory=list)


class Player:
    """Plays one `Utterance` at a time through a sounddevice OutputStream."""

    def __init__(self, device: int | None = None, *, open_stream: bool = True) -> None:
        self.device = device
        self._lock = threading.Lock()
        self._utt: Utterance | None = None
        self._pos = 0
        self._gain = 1.0
        self._target = 1.0
        self._done = threading.Event()
        self._done.set()
        self.log = PlaybackLog()
        self._stream: sd.OutputStream | None = None
        if open_stream:  # tests drive _callback directly without an audio device
            self._stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                           blocksize=256, device=device, callback=self._callback,
                                           latency="low")
            self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
        out = np.zeros(frames, dtype=np.float32)
        with self._lock:
            utt = self._utt
            if utt is not None and not self._done.is_set():
                if self.log.start_ns is None:
                    self.log.start_ns = now_ns()
                n = min(frames, len(utt.pcm) - self._pos)
                chunk = utt.pcm[self._pos:self._pos + n].astype(np.float32) / 32768.0
                gains = ramp(self._gain, self._target, n)
                self._gain = float(gains[-1]) if n else self._gain
                out[:n] = chunk * gains
                self._pos += n
                if self._pos >= len(utt.pcm):
                    self.log.end_ns = now_ns()
                    self._done.set()
        outdata[:, 0] = out

    def play(self, utt: Utterance) -> None:
        """Start playing `utt` (replaces anything playing)."""
        with self._lock:
            self._utt, self._pos = utt, 0
            self._gain = self._target = 1.0
            self.log = PlaybackLog()
            self._done.clear()

    def duck(self, gain: float = 0.25) -> None:
        with self._lock:
            self._target = gain
            self.log.duck_ns.append(now_ns())

    def restore(self) -> None:
        with self._lock:
            self._target = 1.0
            self.log.restore_ns.append(now_ns())

    def stop(self) -> None:
        with self._lock:
            if not self._done.is_set():
                self.log.stopped_ns = now_ns()
                self._done.set()

    @property
    def output_latency(self) -> float:
        """Device output latency reported by PortAudio (seconds)."""
        return float(self._stream.latency) if self._stream is not None else 0.0

    @property
    def playing(self) -> bool:
        return not self._done.is_set()

    @property
    def position(self) -> int:
        """Samples handed to the audio device so far."""
        return self._pos

    def heard_text(self) -> str:
        """Text of every chunk that has started playing (what the caller has heard)."""
        utt = self._utt
        if utt is None:
            return ""
        k = utt.chunk_at(self._pos)
        return " ".join(utt.texts[: k + 1])

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)
