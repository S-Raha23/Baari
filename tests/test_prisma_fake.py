"""Prisma client against a local fake server (no credits): headers, framing, commit, alignment."""

import asyncio
import json

import websockets

from baari.audio.wavio import frames
from baari.config import PrismaConfig
from baari.spikes import align, commit_frames
from baari.stt.prisma_stream import build_headers, stream_frames
from baari.vad.energy import energy_segments


async def _fake_prisma(ws, seen):
    seen["headers"] = dict(ws.request.headers)
    await ws.send(json.dumps({"type": "connected", "config": {"sample_rate": 16000, "chunk_size": 512}}))
    seg = 0
    async for msg in ws:
        if isinstance(msg, bytes):
            seen.setdefault("sizes", set()).add(len(msg))
            seen["n"] = seen.get("n", 0) + 1
        elif json.loads(msg).get("type") == "commit":
            seg += 1
            await ws.send(json.dumps({"type": "processing"}))
            await asyncio.sleep(0.05)
            await ws.send(json.dumps({"type": "transcript", "text": f"seg{seg}", "segment_index": seg,
                                      "latency": 50, "audio_duration_ms": 400, "is_final": True}))


def test_commit_mode_against_fake_server(speech_like):
    seen: dict = {}

    async def main():
        async with websockets.serve(lambda ws: _fake_prisma(ws, seen), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            segs = energy_segments(speech_like, pause_min_ms=120)
            fr = frames(speech_like)
            res = await stream_frames(fr, build_headers(PrismaConfig(), "k", min_silence_ms=2000),
                                      url=f"ws://127.0.0.1:{port}", commit_after_frame=commit_frames(segs, 120),
                                      drain_s=1.0, expect_transcripts=3, log=False)
            return segs, fr, res

    segs, fr, res = asyncio.run(main())
    assert seen["headers"]["x-min-silence-ms"] == "2000"
    assert seen["headers"]["model"] == "prisma-v3.0"
    assert seen["sizes"] == {1024} and seen["n"] == len(fr)
    assert len(res.commits_ms) == 3
    for c, s in zip(res.commits_ms, segs):  # commit sent C ms (rounded up to a frame) after onset
        assert 120 <= c - s.end_ms < 120 + 32
    rows = align(res, segs)
    assert [r["text"] for r in rows] == ["seg1", "seg2", "seg3"]
    for r, s in zip(rows, segs):
        assert r["pause_onset_ms"] == s.end_ms
        # real-time pacing: text arrives ~C + 50 ms (+ scheduling slack) after onset
        assert 120 <= r["text_after_onset_ms"] < 400
