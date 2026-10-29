"""Raw-websockets client for Gnani Prisma streaming STT (the word lane).

Prisma returns text only when a segment closes (no partials). Baari closes segments either by
sending `{"type": "commit"}` after a local pause of C ms (commit mode) or by connecting with a
low `x-min-silence-ms` so Prisma's own VAD closes them (fallback mode). Every received message
is stamped with the shared monotonic clock so arrival times can be measured against local
pause onsets.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import websockets

from baari.clock import now_ns
from baari.config import FRAME_MS, PrismaConfig
from baari.usage import log_usage


def build_headers(cfg: PrismaConfig, api_key: str, *, min_silence_ms: int | None = None) -> dict[str, str]:
    """WebSocket upgrade headers for one Prisma session (VAD settings are fixed per connection)."""
    return {
        "x-api-key-id": api_key,
        "language_code": cfg.language_code,
        "model": cfg.model,
        "format": cfg.format,
        "x-sample-rate": str(cfg.sample_rate),
        "x-vad-threshold": str(cfg.vad_threshold),
        "x-min-silence-ms": str(min_silence_ms if min_silence_ms is not None else cfg.min_silence_ms),
        "x-min-speech-ms": str(cfg.min_speech_ms),
        "x-min-segment-ms": str(cfg.min_segment_ms),
        "x-idle-timeout-sec": str(cfg.idle_timeout_sec),
    }


def redacted(headers: dict[str, str]) -> dict[str, str]:
    """Headers without the API key (safe to log, hash and cache)."""
    return {k: v for k, v in headers.items() if k.lower() != "x-api-key-id"}


@dataclass
class PrismaEvent:
    """One server message, stamped on receipt (ns on the shared clock)."""

    t_ns: int
    msg: dict[str, Any]

    @property
    def type(self) -> str:
        return str(self.msg.get("type", ""))


@dataclass
class StreamResult:
    """Everything observed while streaming one clip."""

    t0_ns: int  # wall-clock instant corresponding to audio time 0
    events: list[PrismaEvent] = field(default_factory=list)
    commits_ms: list[float] = field(default_factory=list)  # audio time at which commit was sent
    send_lag_ms_max: float = 0.0  # worst lateness of a frame vs its real-time schedule

    def rel_ms(self, t_ns: int) -> float:
        """Convert a clock value to ms of audio time since the start of the clip."""
        return (t_ns - self.t0_ns) / 1e6

    def transcripts(self) -> list[PrismaEvent]:
        return [e for e in self.events if e.type == "transcript"]

    def to_json(self) -> dict[str, Any]:
        return {
            "events": [{"t_ms": self.rel_ms(e.t_ns), "msg": e.msg} for e in self.events],
            "commits_ms": self.commits_ms,
            "send_lag_ms_max": self.send_lag_ms_max,
        }


async def stream_frames(
    frames: list[bytes],
    headers: dict[str, str],
    *,
    url: str,
    commit_after_frame: Iterable[int] = (),
    pace: bool = True,
    drain_s: float = 4.0,
    expect_transcripts: int | None = None,
    log: bool = True,
) -> StreamResult:
    """Stream 1,024-byte frames at real-time cadence; collect every server message.

    Frame k is sent when it would have finished arriving from a microphone, i.e. at
    t0 + (k + 1) * 32 ms, so audio time and wall-clock time line up. A commit is sent right
    after each frame index in `commit_after_frame`. After the last frame, keep listening for
    `drain_s` seconds (or until `expect_transcripts` transcripts have arrived).
    """
    commit_set = set(commit_after_frame)
    frame_s = FRAME_MS / 1000.0
    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        result = StreamResult(t0_ns=now_ns())
        done = asyncio.Event()

        async def receive() -> None:
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    ev = PrismaEvent(now_ns(), json.loads(raw))
                    result.events.append(ev)
                    if ev.type == "error":
                        print(f"[prisma] error: {ev.msg.get('message')}")
                    if expect_transcripts and len(result.transcripts()) >= expect_transcripts:
                        done.set()
            except websockets.ConnectionClosed:
                pass
            finally:
                done.set()

        rx = asyncio.create_task(receive())
        # Wait for `connected` before streaming so t0 reflects the start of audio.
        for _ in range(100):
            if result.events or rx.done():
                break
            await asyncio.sleep(0.02)
        result.t0_ns = now_ns()
        for k, frame in enumerate(frames):
            if pace:
                due = result.t0_ns + int((k + 1) * frame_s * 1e9)
                delay = (due - now_ns()) / 1e9
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    result.send_lag_ms_max = max(result.send_lag_ms_max, -delay * 1000)
            await ws.send(frame)
            if k in commit_set:
                await ws.send(json.dumps({"type": "commit"}))
                result.commits_ms.append((k + 1) * FRAME_MS)
        try:
            await asyncio.wait_for(done.wait(), timeout=drain_s)
        except asyncio.TimeoutError:
            pass
        await ws.close()
        try:
            await asyncio.wait_for(rx, timeout=2.0)
        except asyncio.TimeoutError:
            rx.cancel()
    if log:
        log_usage("prisma.stream", audio_seconds=len(frames) * frame_s,
                  config=redacted(headers), commits=len(result.commits_ms))
    return result
