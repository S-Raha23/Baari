"""`python -m baari check-session`: sanity-check a recorded session before labelling.

Prints metadata, audio health (duration, dropped blocks, clipping, measured sample rate) and,
per trial, what the local VAD found in the answer window (turns) or during the bot's speech
(barge-in). Problems are listed at the end so a bad session is caught right away.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from baari.audio.wavio import load_wav
from baari.collect.recorder import t_to_sample
from baari.config import SAMPLE_RATE
from baari.vad.silero import run_vad


def load_session(d: Path) -> tuple[dict[str, Any], list[dict[str, Any]], np.ndarray]:
    meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    pcm = load_wav(d / "mic.wav")
    return meta, events, pcm


def _ms(t_ns: int, fit: tuple[float, float]) -> float:
    return t_to_sample(t_ns, fit) / SAMPLE_RATE * 1000.0


def check_session(d: Path) -> list[str]:
    meta, events, pcm = load_session(d)
    problems: list[str] = []
    print(f"session {meta['session_id']}  speaker {meta['speaker_id']}  kind {meta['kind']}  "
          f"condition {meta.get('condition')}")
    print(f"input: {meta.get('input_device')}  output: {meta.get('output_device')}")
    dur = len(pcm) / SAMPLE_RATE
    print(f"audio {dur:.1f} s, overflows {meta.get('input_overflows')}, peak {meta.get('peak_level')}, "
          f"measured rate {meta.get('clock_fit', {}).get('rate_hz_measured')} Hz, complete {meta.get('complete')}")
    if not meta.get("complete"):
        problems.append("session.json not completed (crash or still recording)")
    if meta.get("input_overflows"):
        problems.append(f"{meta['input_overflows']} input overflows (dropped audio)")
    if (meta.get("peak_level") or 0) >= 32700:
        problems.append("clipping detected")
    rate = meta.get("clock_fit", {}).get("rate_hz_measured")
    if rate and abs(rate - SAMPLE_RATE) > 50:
        problems.append(f"measured sample rate {rate} Hz far from 16000")
    fit = (meta["clock_fit"]["a_samples_per_ns"], meta["clock_fit"]["b_samples"])
    kinds: dict[str, int] = {}
    for e in events:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    print("events:", ", ".join(f"{k}={v}" for k, v in kinds.items()))

    _, vad_events = run_vad(pcm)
    segs = []
    start = None
    for ev in vad_events:
        if ev.kind == "speech_start":
            start = ev.onset_ms
        elif ev.kind == "pause_start" and start is not None:
            segs.append((start, ev.onset_ms))
            start = None
    if start is not None:
        segs.append((start, dur * 1000))
    level = 20 * np.log10(np.sqrt(np.mean((pcm.astype(np.float64) / 32768) ** 2)) + 1e-9)
    print(f"VAD: {len(segs)} speech segments, {sum(b - a for a, b in segs) / 1000:.1f} s of speech; "
          f"overall level {level:.1f} dBFS")

    if meta["kind"] in ("turns", "bargein"):
        bot = {e["trial"]: e for e in events if e["type"] == "bot_done"}
        ends = {e["trial"]: e for e in events if e["type"] in ("done", "trial_ok")}
        redo = [e["trial"] for e in events if e["type"] == "trial_redo"]
        print(f"\ntrials completed {len(ends)}, redone {len(redo)}")
        print(" trial | window s | segments | pauses | first speech ms | last speech → end ms | info")
        for trial, end_ev in sorted(ends.items()):
            b = [e for e in events if e["type"] == "bot_done" and e["trial"] == trial][-1] if trial in bot else None
            if b is None or b.get("playback_start_ns") is None:
                problems.append(f"trial {trial}: no playback timestamps")
                continue
            if meta["kind"] == "turns":
                w0, w1 = _ms(b["playback_end_ns"], fit), _ms(end_ev["t_ns"], fit)
                info = b.get("slot", "")
            else:
                w0, w1 = _ms(b["playback_start_ns"], fit), _ms(end_ev["t_ns"], fit)
                info = b.get("action", "")
            inside = [(a, c) for a, c in segs if c > w0 and a < w1]
            first = inside[0][0] - w0 if inside else None
            gap_end = w1 - inside[-1][1] if inside else None
            print(f" {trial:5d} | {(w1 - w0) / 1000:8.1f} | {len(inside):8d} | {max(0, len(inside) - 1):6d} | "
                  f"{'–' if first is None else f'{first:.0f}':>15} | {'–' if gap_end is None else f'{gap_end:.0f}':>20} | {info}")
            if meta["kind"] == "turns" and not inside:
                problems.append(f"trial {trial}: no speech found in the answer window")
            if meta["kind"] == "turns" and gap_end is not None and gap_end < 0:
                problems.append(f"trial {trial}: Done pressed while still speaking")
            if meta["kind"] == "bargein" and info in ("backchannel", "interrupt", "interrupt_polite") and not inside:
                problems.append(f"trial {trial}: action '{info}' but no speech during the bot")
    print("\nPROBLEMS:" if problems else "\nNo problems found.")
    for p in problems:
        print("  - " + p)
    return problems
