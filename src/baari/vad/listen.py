"""`python -m baari listen`: print local-lane speech/pause events, live from the mic or from a WAV.

Each line shows the audio-time onset, how long after the onset the event was detected, and
(for pauses) the segment that just ended. Per-frame VAD compute time is reported at the end.
"""

from __future__ import annotations

import time

import numpy as np

from baari.audio.wavio import load_wav
from baari.clock import now_ns
from baari.config import FRAME_SAMPLES, BaariConfig
from baari.vad.silero import PauseTracker, SileroVAD, VadEvent


def _print_event(ev: VadEvent) -> None:
    delay = ev.detected_ms - ev.onset_ms
    if ev.kind == "speech_start":
        print(f"{ev.onset_ms / 1000:8.2f}s  SPEECH   (detected +{delay:.0f} ms)")
    elif ev.kind == "silence_start":
        print(f"{ev.onset_ms / 1000:8.2f}s  silence? (detected +{delay:.0f} ms)")
    elif ev.kind == "silence_cancel":
        print(f"{ev.onset_ms / 1000:8.2f}s  ...speech resumed (no pause)")
    else:
        seg = ev.onset_ms - (ev.segment_start_ms or 0.0)
        print(f"{ev.onset_ms / 1000:8.2f}s  PAUSE    (detected +{delay:.0f} ms, segment {seg:.0f} ms)")


def listen(cfg: BaariConfig, *, wav: str | None, seconds: float, phone: bool, snr_db: float | None,
           device: int | None) -> None:
    vad = SileroVAD()
    tracker = PauseTracker(pause_min_ms=cfg.pause_min_ms)
    compute_ns: list[int] = []

    def step(frame: np.ndarray, t_ns: int) -> None:
        t0 = now_ns()
        p = vad.prob(frame)
        compute_ns.append(now_ns() - t0)
        for ev in tracker.update(p, t_ns):
            _print_event(ev)

    if wav:
        pcm = load_wav(wav)
        if phone:
            from baari.audio.telephony import simulate_phone

            pcm = simulate_phone(pcm, snr_db=snr_db)
        print(f"{wav}: {len(pcm) / 16000:.1f} s{' (telephone simulation)' if phone else ''}")
        for k in range(len(pcm) // FRAME_SAMPLES):
            step(pcm[k * FRAME_SAMPLES:(k + 1) * FRAME_SAMPLES], 0)
    else:
        from baari.audio.capture import MicCapture

        print(f"Listening for {seconds:.0f} s — try: \"haan… matlab… theek hai\" (Ctrl+C to stop)")
        end = time.monotonic() + seconds
        with MicCapture(device=device) as mic:
            try:
                while time.monotonic() < end:
                    block = mic.read()
                    step(block.pcm, block.t_ns)
            except KeyboardInterrupt:
                pass
            if mic.overflows:
                print(f"warning: {mic.overflows} input overflows (dropped audio)")
    if compute_ns:
        arr = np.array(compute_ns) / 1e6
        print(f"\nVAD compute per 32 ms frame: median {np.median(arr):.2f} ms, p99 {np.percentile(arr, 99):.2f} ms "
              f"({len(arr)} frames)")
