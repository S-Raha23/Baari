"""Clock, config, usage log, cache keys, framing and the CLI parser."""

import json

import numpy as np
import pytest

from baari import config as C
from baari.__main__ import build_parser
from baari.audio.wavio import frames, load_wav, save_wav
from baari.clock import ms_since, now_ns
from baari.stt.prisma_stream import build_headers, redacted
from baari.usage import BudgetExceeded, log_usage, require_confirmation, stable_hash, usage_summary


def test_clock_monotonic():
    a = now_ns()
    b = now_ns()
    assert b >= a and ms_since(a) >= 0


def test_frames_exact_1024_bytes():
    pcm = np.arange(1500, dtype=np.int16)
    fr = frames(pcm)
    assert len(fr) == 3 and all(len(f) == 1024 for f in fr)
    assert np.frombuffer(fr[0], "<i2")[5] == 5
    assert np.frombuffer(fr[2], "<i2")[-1] == 0  # zero padding


def test_wav_roundtrip_and_resample(tmp_path):
    x = (np.sin(np.linspace(0, 100, 8000)) * 10000).astype(np.int16)
    save_wav(tmp_path / "a.wav", x, sr=8000)
    y = load_wav(tmp_path / "a.wav", sr=16000)
    assert y.dtype == np.int16 and abs(len(y) - 16000) <= 2


def test_usage_log_and_summary(tmp_path):
    p = tmp_path / "usage.jsonl"
    log_usage("prisma.stream", audio_seconds=6.0, path=p)
    log_usage("timbre.rest", characters=40, path=p)
    log_usage("timbre.rest", characters=10, path=p)
    s = usage_summary(p)
    assert s["prisma.stream"]["audio_seconds"] == 6.0
    assert s["timbre.rest"] == {"calls": 2, "audio_seconds": 0.0, "characters": 50}
    assert "timestamp" in json.loads(p.read_text().splitlines()[0])


def test_budget_gate():
    require_confirmation(50, threshold=50, confirmed=False, what="job")
    with pytest.raises(BudgetExceeded):
        require_confirmation(51, threshold=50, confirmed=False, what="job")
    require_confirmation(51, threshold=50, confirmed=True, what="job")


def test_stable_hash_sensitive_to_config():
    a = stable_hash(b"audio", {"x": 1})
    assert a == stable_hash(b"audio", {"x": 1})
    assert a != stable_hash(b"audio", {"x": 2})
    assert a != stable_hash(b"audi", {"x": 1})


def test_headers_redaction_never_leaks_key():
    h = build_headers(C.PrismaConfig(), "SECRET", min_silence_ms=200)
    assert h["x-min-silence-ms"] == "200" and h["x-api-key-id"] == "SECRET"
    assert "SECRET" not in json.dumps(redacted(h))


def test_config_yaml_override(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("commit_delay_ms: 150\nprisma:\n  model: prisma-v2.5\n")
    cfg = C.load_config(p)
    assert cfg.commit_delay_ms == 150 and cfg.prisma.model == "prisma-v2.5"
    p.write_text("nope: 1\n")
    with pytest.raises(KeyError):
        C.load_config(p)


def test_cli_parses_spikes():
    args = build_parser().parse_args(["spike-stt", "--modes", "commit", "--repeats", "1"])
    assert args.command == "spike-stt" and args.repeats == 1
