"""M0 API spikes: measure Prisma commit vs fallback mode, and Timbre REST vs WebSocket.

`spike-stt` streams a clip through Prisma twice (commit mode and fallback mode) and reports,
for every segment, when `processing` and the transcript arrived relative to the local pause
onset. By default the clip is synthetic: three Hinglish phrases spoken by Timbre (cached),
joined with known silences, so no personal audio is needed.

`spike-tts` synthesises one Hinglish sentence via REST and via WebSocket and reports time to
first audio. Both spikes write raw results to data/cache/spikes/ and a generated Markdown
summary to reports/spikes/ (numbers are never typed by hand).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from baari.audio.wavio import frames, load_wav, save_wav, silence
from baari.config import CACHE_DIR, FRAME_MS, REPO_ROOT, BaariConfig, get_api_key
from baari.stt import cache as stt_cache
from baari.stt.prisma_stream import StreamResult, build_headers, redacted, stream_frames
from baari.tts.cache import get_or_synth
from baari.tts.timbre import synth_rest, synth_ws
from baari.vad.energy import Segment, energy_segments

SPIKE_DIR = CACHE_DIR / "spikes"
REPORT_DIR = REPO_ROOT / "reports" / "spikes"

SPIKE_PHRASES = ["Mera loan ka EMI", "matlab pichle mahine ka", "do baar kat gaya hai."]
SPIKE_GAPS_MS = [700, 900]
LEAD_MS, TAIL_MS = 500, 2500
TTS_SENTENCE = "Ji, main samajh gayi. Aapka EMI do baar kat gaya hai, main abhi check karti hoon."


def build_spike_clip(cfg: BaariConfig, api_key: str) -> np.ndarray:
    """Synthetic test clip: Timbre phrases joined by known silences (cached TTS)."""
    parts = [silence(LEAD_MS)]
    for i, text in enumerate(SPIKE_PHRASES):
        parts.append(get_or_synth(text, cfg.timbre, api_key))
        parts.append(silence(SPIKE_GAPS_MS[i] if i < len(SPIKE_GAPS_MS) else TAIL_MS))
    return np.concatenate(parts)


def commit_frames(segs: list[Segment], commit_delay_ms: float) -> list[int]:
    """Frame index after which to send `commit`: C ms after each local pause onset."""
    extra = int(np.ceil(commit_delay_ms / FRAME_MS))
    return [int(round(s.end_ms / FRAME_MS)) + extra - 1 for s in segs]


def align(result: StreamResult, segs: list[Segment]) -> list[dict[str, Any]]:
    """Pair each transcript with the local pause onset it most plausibly closes.

    The reference onset is the latest local pause onset at or before the `processing` message
    that preceded the transcript (or the transcript itself if no `processing` came first).
    """
    onsets = [s.end_ms for s in segs]
    rows = []
    last_proc_ms: float | None = None
    for ev in result.events:
        t = result.rel_ms(ev.t_ns)
        if ev.type == "processing":
            last_proc_ms = t
        elif ev.type == "transcript":
            ref_t = last_proc_ms if last_proc_ms is not None else t
            prior = [o for o in onsets if o <= ref_t]
            onset = prior[-1] if prior else None
            rows.append({
                "text": ev.msg.get("text", ""),
                "segment_index": ev.msg.get("segment_index"),
                "audio_duration_ms": ev.msg.get("audio_duration_ms"),
                "latency_ms": ev.msg.get("latency"),
                "pause_onset_ms": onset,
                "processing_after_onset_ms": None if (onset is None or last_proc_ms is None) else last_proc_ms - onset,
                "text_after_onset_ms": None if onset is None else t - onset,
            })
            last_proc_ms = None
    return rows


def _median(xs: list[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return statistics.median(vals) if vals else None


def _fmt(x: Any) -> str:
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.0f}"
    return str(x)


async def _run_stt(cfg: BaariConfig, api_key: str, pcm: np.ndarray, segs: list[Segment],
                   mode: str) -> dict[str, Any]:
    if mode == "commit":
        # Prisma's own VAD set to its maximum so segment closes come from our commits.
        headers = build_headers(cfg.prisma, api_key, min_silence_ms=2000)
        plan = {"mode": "commit", "commit_delay_ms": cfg.commit_delay_ms}
        commits = commit_frames(segs, cfg.commit_delay_ms)
    else:
        headers = build_headers(cfg.prisma, api_key, min_silence_ms=cfg.fallback_min_silence_ms)
        plan = {"mode": "fallback"}
        commits = []
    fr = frames(pcm)
    result = await stream_frames(fr, headers, url=cfg.prisma.url, commit_after_frame=commits,
                                 drain_s=5.0)
    rows = align(result, segs)
    entry = {
        "mode": mode, "plan": plan, "config": redacted(headers),
        "pause_onsets_ms": [s.end_ms for s in segs],
        "segments": rows, "raw": result.to_json(),
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    key = stt_cache.stt_key(pcm.astype("<i2").tobytes(), redacted(headers), plan)
    stt_cache.save(key, entry)
    return entry


def run_stt_spike(cfg: BaariConfig, *, wav: str | None, modes: list[str], repeats: int) -> Path:
    """Run the STT spike against the real API and write reports/spikes/stt_spike.md."""
    api_key = get_api_key()
    if wav:
        pcm = load_wav(wav)
        clip_desc = f"`{Path(wav).name}` (user-supplied, {len(pcm) / 16000:.1f} s)"
    else:
        pcm = build_spike_clip(cfg, api_key)
        save_wav(SPIKE_DIR / "spike_clip.wav", pcm)
        clip_desc = (f"synthetic Timbre clip ({cfg.timbre.voice}, {cfg.timbre.model}): "
                     + " / ".join(f"\"{p}\"" for p in SPIKE_PHRASES)
                     + f", gaps {SPIKE_GAPS_MS} ms, {len(pcm) / 16000:.1f} s")
    segs = energy_segments(pcm, pause_min_ms=cfg.commit_delay_ms)
    print(f"clip: {clip_desc}")
    print("local pause onsets (ms):", [round(s.end_ms) for s in segs])

    runs: list[dict[str, Any]] = []
    for r in range(repeats):
        for mode in modes:
            print(f"\n== {mode} mode, run {r + 1}/{repeats} ==")
            entry = asyncio.run(_run_stt(cfg, api_key, pcm, segs, mode))
            runs.append(entry)
            for row in entry["segments"]:
                print(f"  onset {_fmt(row['pause_onset_ms']):>6} ms | processing +{_fmt(row['processing_after_onset_ms']):>5} "
                      f"| text +{_fmt(row['text_after_onset_ms']):>5} | latency {_fmt(row['latency_ms']):>4} | {row['text']}")
            errors = [e["msg"] for e in entry["raw"]["events"] if e["msg"].get("type") == "error"]
            if errors:
                print("  errors:", errors)
    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (SPIKE_DIR / f"stt_spike_{stamp}.json").write_text(
        json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    return _write_stt_report(cfg, clip_desc, segs, runs)


def _write_stt_report(cfg: BaariConfig, clip_desc: str, segs: list[Segment],
                      runs: list[dict[str, Any]]) -> Path:
    lines = [
        "# Prisma STT spike (generated by `python -m baari spike-stt`)",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M %z')}. Clip: {clip_desc}.",
        f"Model `{cfg.prisma.model}`, language `{cfg.prisma.language_code}`, format `{cfg.prisma.format}`, "
        f"commit delay C = {cfg.commit_delay_ms} ms, fallback `x-min-silence-ms` = {cfg.fallback_min_silence_ms}.",
        f"Local pause onsets (energy VAD, ms): {[round(s.end_ms) for s in segs]}.",
        "",
        "All times are ms after the local pause onset the segment ends at (audio clock = wall clock,",
        "frames sent at real-time cadence).",
        "",
        "## Summary",
        "",
        "| Mode | Runs | Transcripts | Median processing after onset | Median text after onset | Median Prisma `latency` |",
        "|---|---|---|---|---|---|",
    ]
    for mode in dict.fromkeys(r["mode"] for r in runs):
        rows = [row for r in runs if r["mode"] == mode for row in r["segments"]]
        n_runs = sum(1 for r in runs if r["mode"] == mode)
        lines.append(
            f"| {mode} | {n_runs} | {len(rows)} | {_fmt(_median([x['processing_after_onset_ms'] for x in rows]))} "
            f"| {_fmt(_median([x['text_after_onset_ms'] for x in rows]))} | {_fmt(_median([x['latency_ms'] for x in rows]))} |")
    lines += ["", "## Per segment", "",
              "| Mode | Run | Onset ms | Processing + | Text + | `latency` | `audio_duration_ms` | Text |",
              "|---|---|---|---|---|---|---|---|"]
    run_no: dict[str, int] = {}
    for r in runs:
        run_no[r["mode"]] = run_no.get(r["mode"], 0) + 1
        for x in r["segments"]:
            lines.append(f"| {r['mode']} | {run_no[r['mode']]} | {_fmt(x['pause_onset_ms'])} | {_fmt(x['processing_after_onset_ms'])} "
                         f"| {_fmt(x['text_after_onset_ms'])} | {_fmt(x['latency_ms'])} | {_fmt(x['audio_duration_ms'])} | {x['text']} |")
        errs = [e["msg"].get("message") for e in r["raw"]["events"] if e["msg"].get("type") == "error"]
        if errs:
            lines.append(f"| {r['mode']} | {run_no[r['mode']]} | error | | | | | {'; '.join(map(str, errs))} |")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "stt_spike.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport: {out}")
    return out


def run_tts_spike(cfg: BaariConfig, *, text: str, repeats: int) -> Path:
    """Synthesise `text` via REST and WebSocket `repeats` times each; write tts_spike.md."""
    api_key = get_api_key()
    rows: list[dict[str, Any]] = []
    for r in range(repeats):
        for transport in ("rest", "ws"):
            if transport == "rest":
                syn = synth_rest(text, cfg.timbre, api_key)
            else:
                syn = asyncio.run(synth_ws(text, cfg.timbre, api_key))
            pcm = np.frombuffer(syn.pcm, dtype="<i2")
            save_wav(SPIKE_DIR / f"tts_{transport}.wav", pcm, syn.sample_rate)
            row = {"transport": transport, "run": r + 1, "first_audio_ms": syn.first_audio_ms,
                   "total_ms": syn.total_ms, "audio_s": syn.duration_s, "chunks": syn.chunks,
                   "connect_ms": getattr(syn, "connect_ms", None)}
            rows.append(row)
            print(f"{transport:>4} run {r + 1}: first audio {syn.first_audio_ms:.0f} ms, total {syn.total_ms:.0f} ms, "
                  f"{syn.duration_s:.2f} s audio, {syn.chunks} chunk(s)")
    SPIKE_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Timbre TTS spike (generated by `python -m baari spike-tts`)",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M %z')}. Text ({len(text)} chars): \"{text}\".",
        f"Model `{cfg.timbre.model}`, voice `{cfg.timbre.voice}`, language `{cfg.timbre.language}`, "
        f"{cfg.timbre.sample_rate} Hz raw PCM. Time measured from request start on the client.",
        "",
        "| Transport | Run | Connect ms | First audio ms | Total ms | Audio s | Chunks |",
        "|---|---|---|---|---|---|---|",
    ]
    for x in rows:
        lines.append(f"| {x['transport']} | {x['run']} | {_fmt(x['connect_ms'])} | {_fmt(x['first_audio_ms'])} "
                     f"| {_fmt(x['total_ms'])} | {x['audio_s']:.2f} | {x['chunks']} |")
    lines += ["", "| Transport | Median first audio ms | Median total ms |", "|---|---|---|"]
    for t in ("rest", "ws"):
        sel = [x for x in rows if x["transport"] == t]
        lines.append(f"| {t} | {_fmt(_median([x['first_audio_ms'] for x in sel]))} | {_fmt(_median([x['total_ms'] for x in sel]))} |")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "tts_spike.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {out}")
    return out


def with_overrides(cfg: BaariConfig, **kw: Any) -> BaariConfig:
    """Copy of cfg with top-level / timbre / prisma overrides applied (None = keep)."""
    tim = {k[7:]: v for k, v in kw.items() if k.startswith("timbre_") and v is not None}
    pri = {k[7:]: v for k, v in kw.items() if k.startswith("prisma_") and v is not None}
    top = {k: v for k, v in kw.items() if not k.startswith(("timbre_", "prisma_")) and v is not None}
    return replace(cfg, timbre=replace(cfg.timbre, **tim), prisma=replace(cfg.prisma, **pri), **top)

