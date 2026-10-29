"""CLI dispatcher: `python -m baari <command>` (see SPEC.md §11).

Commands that belong to later milestones are registered but report which milestone builds them.
"""

from __future__ import annotations

import argparse
import sys

from baari.config import load_config

PLANNED = {
    "collect": "M2", "label": "M3", "audit-labels": "M3", "transcribe-cache": "M3",
    "train": "M5", "eval": "M4", "report": "M8", "serve": "M7", "replay": "M7",
    "delete-speaker": "M2",
}


def _cmd_spike_stt(args: argparse.Namespace) -> int:
    from baari.spikes import run_stt_spike, with_overrides

    cfg = with_overrides(load_config(args.config), commit_delay_ms=args.commit_ms,
                         prisma_model=args.model, prisma_language_code=args.language,
                         prisma_format=args.format)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    run_stt_spike(cfg, wav=args.wav, modes=modes, repeats=args.repeats)
    return 0


def _cmd_spike_tts(args: argparse.Namespace) -> int:
    from baari.spikes import TTS_SENTENCE, run_tts_spike, with_overrides

    cfg = with_overrides(load_config(args.config), timbre_model=args.model,
                         timbre_voice=args.voice, timbre_language=args.language)
    run_tts_spike(cfg, text=args.text or TTS_SENTENCE, repeats=args.repeats)
    return 0


def _cmd_devices(args: argparse.Namespace) -> int:
    import sounddevice as sd

    print(sd.query_devices())
    print(f"\ndefault input/output: {sd.default.device}")
    return 0


def _cmd_listen(args: argparse.Namespace) -> int:
    from baari.vad.listen import listen

    listen(load_config(args.config), wav=args.wav, seconds=args.seconds, phone=args.phone,
           snr_db=args.snr, device=args.device)
    return 0


def _cmd_usage(args: argparse.Namespace) -> int:
    from baari.usage import usage_summary

    summary = usage_summary()
    if not summary:
        print("no API usage logged yet")
    for endpoint, agg in sorted(summary.items()):
        print(f"{endpoint:16s} calls={agg['calls']:<5.0f} audio_s={agg['audio_seconds']:<8.1f} chars={agg['characters']:.0f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="baari", description="Baari — knows when it's your turn.")
    p.add_argument("--config", help="YAML config override (default: baari.yaml if present)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("spike-stt", help="M0: stream a clip through Prisma in commit and fallback mode")
    s.add_argument("--wav", help="clip to stream (default: synthetic Timbre clip)")
    s.add_argument("--modes", default="commit,fallback")
    s.add_argument("--repeats", type=int, default=2)
    s.add_argument("--commit-ms", type=int, help="commit delay C (ms)")
    s.add_argument("--model", help="Prisma model, e.g. prisma-v2.5")
    s.add_argument("--language", help="language_code, e.g. hi-IN")
    s.add_argument("--format", help="verbatim | transcribe | codemix | transliterate")
    s.set_defaults(func=_cmd_spike_stt)

    s = sub.add_parser("spike-tts", help="M0: time to first audio, Timbre REST vs WebSocket")
    s.add_argument("--text")
    s.add_argument("--repeats", type=int, default=3)
    s.add_argument("--model")
    s.add_argument("--voice")
    s.add_argument("--language")
    s.set_defaults(func=_cmd_spike_tts)

    s = sub.add_parser("devices", help="list audio devices")
    s.set_defaults(func=_cmd_devices)

    s = sub.add_parser("listen", help="M1: print live speech/pause events (mic, or --wav)")
    s.add_argument("--wav")
    s.add_argument("--seconds", type=float, default=20.0)
    s.add_argument("--phone", action="store_true", help="apply telephone simulation (--wav only)")
    s.add_argument("--snr", type=float, help="noise SNR in dB for --phone")
    s.add_argument("--device", type=int, help="input device index (see `devices`)")
    s.set_defaults(func=_cmd_listen)

    s = sub.add_parser("usage", help="summarise logged API usage (credits)")
    s.set_defaults(func=_cmd_usage)

    for name, milestone in PLANNED.items():
        s = sub.add_parser(name, help=f"(built in {milestone})")
        s.set_defaults(func=lambda a, n=name, m=milestone: (print(f"'{n}' is built in milestone {m}."), 2)[1])
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Devanagari transcripts on a Windows console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
