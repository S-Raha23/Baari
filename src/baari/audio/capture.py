"""Microphone capture: 16 kHz mono int16 in 512-sample blocks, each stamped on the shared clock.

Blocks go into a thread-safe queue for the consumer (VAD, Prisma, recorder) and into a ring
buffer that keeps the last few seconds (pre-roll for recordings and barge-in analysis).
"""

from __future__ import annotations

import queue
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from baari.clock import now_ns
from baari.config import FRAME_SAMPLES, SAMPLE_RATE


@dataclass
class Block:
    """One captured 32 ms block."""

    index: int  # running block number since capture start
    t_ns: int  # shared-clock time when the block was delivered
    pcm: np.ndarray  # int16, FRAME_SAMPLES long


class MicCapture:
    """Context manager around a sounddevice InputStream.

    `overflows` counts blocks the audio driver reported as dropped; the consumer should
    report it, because dropped audio breaks timing.
    """

    def __init__(self, device: int | str | None = None, ring_seconds: float = 10.0) -> None:
        self.device = device
        self.queue: queue.Queue[Block] = queue.Queue()
        self.ring: deque[Block] = deque(maxlen=int(ring_seconds * SAMPLE_RATE / FRAME_SAMPLES))
        self.overflows = 0
        self._n = 0
        self._stream: sd.InputStream | None = None

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ANN001
        t = now_ns()
        if status.input_overflow:
            self.overflows += 1
        block = Block(self._n, t, indata[:, 0].copy())
        self._n += 1
        self.ring.append(block)
        self.queue.put(block)

    def __enter__(self) -> "MicCapture":
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                      blocksize=FRAME_SAMPLES, device=self.device,
                                      callback=self._callback, latency="low")
        self._stream.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self, timeout: float = 1.0) -> Block:
        """Next block (blocks until available)."""
        return self.queue.get(timeout=timeout)
