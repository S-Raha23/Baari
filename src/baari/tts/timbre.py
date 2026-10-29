"""Gnani Timbre TTS client: REST (full audio) and WebSocket (streamed base64 chunks).

Both return raw 16-bit mono PCM at `cfg.sample_rate` plus timing on the shared clock:
time to first audio byte and total time. Every call is logged to the usage log.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import httpx
import websockets

from baari.clock import ms_since, now_ns
from baari.config import TimbreConfig
from baari.usage import log_usage


class TimbreError(RuntimeError):
    """Timbre returned an error message or a non-200 status."""


@dataclass
class Synthesis:
    """Raw PCM (int16 LE mono) and timing for one synthesis."""

    pcm: bytes
    sample_rate: int
    first_audio_ms: float
    total_ms: float
    transport: str
    chunks: int = 1

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate


def as_pcm(audio: bytes, sample_rate: int) -> bytes:
    """Return raw int16 PCM even if the server sent a WAV container despite container=raw."""
    if audio[:4] == b"RIFF":
        from baari.audio.wavio import load_wav

        return load_wav(audio, sample_rate).astype("<i2").tobytes()
    return audio


def request_body(text: str, cfg: TimbreConfig, container: str = "raw") -> dict[str, Any]:
    """JSON request shared by REST, SSE and WebSocket (see docs/API_NOTES.md)."""
    return {
        "text": text,
        "voice": cfg.voice,
        "model": cfg.model,
        "language": cfg.language,
        "speed": cfg.speed,
        "audio_config": {
            "sample_rate": cfg.sample_rate,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": container,
        },
    }


def synth_rest(text: str, cfg: TimbreConfig, api_key: str, *, timeout_s: float = 60.0) -> Synthesis:
    """POST /tts/inference with container=raw; first-audio = first response body byte."""
    t0 = now_ns()
    first = None
    buf = bytearray()
    headers = {"X-API-Key-ID": api_key, "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout_s) as client:
        with client.stream("POST", cfg.rest_url, headers=headers, json=request_body(text, cfg)) as r:
            if r.status_code != 200:
                r.read()
                log_usage("timbre.rest", characters=len(text), status=r.status_code)
                raise TimbreError(f"REST {r.status_code}: {r.text[:300]}")
            for chunk in r.iter_bytes():
                if chunk and first is None:
                    first = ms_since(t0)
                buf.extend(chunk)
    total = ms_since(t0)
    log_usage("timbre.rest", characters=len(text), voice=cfg.voice, model=cfg.model)
    return Synthesis(as_pcm(bytes(buf), cfg.sample_rate), cfg.sample_rate, first or total, total, "rest")


async def synth_ws(text: str, cfg: TimbreConfig, api_key: str, *, timeout_s: float = 60.0) -> Synthesis:
    """WebSocket /api/v1/tts: one request, base64 audio chunks until `complete`."""
    headers = {"X-API-Key-ID": api_key}
    t0 = now_ns()
    first = None
    buf = bytearray()
    n = 0
    async with websockets.connect(cfg.ws_url, additional_headers=headers, max_size=None,
                                  open_timeout=timeout_s) as ws:
        t_open = ms_since(t0)
        await ws.send(json.dumps(request_body(text, cfg)))
        async for raw in ws:
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "audio":
                audio = base64.b64decode(msg["data"]["audio"])
                if audio:
                    if first is None:
                        first = ms_since(t0)
                    buf.extend(audio)
                    n += 1
            elif kind == "complete":
                break
            elif kind == "error":
                log_usage("timbre.ws", characters=len(text), status="error")
                raise TimbreError(f"WS error: {msg.get('message')}")
    total = ms_since(t0)
    log_usage("timbre.ws", characters=len(text), voice=cfg.voice, model=cfg.model)
    syn = Synthesis(as_pcm(bytes(buf), cfg.sample_rate), cfg.sample_rate, first or total, total, "ws", chunks=n)
    syn.connect_ms = t_open  # type: ignore[attr-defined]
    return syn
