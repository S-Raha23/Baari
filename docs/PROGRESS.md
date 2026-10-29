# Progress

## M0 — Setup and API spike (in progress)

**Works**
- Project skeleton (`src/baari/`, `pyproject.toml` with pinned versions, `.gitignore` covering
  `.venv/`, `.env`, `data/raw/`, `data/cache/` and all audio, `.env.example`).
- CLI `python -m baari` with `spike-stt`, `spike-tts`, `devices`, `usage`; later-milestone
  commands registered as placeholders.
- Prisma streaming client (raw `websockets`, exact 1,024-byte frames at real-time cadence,
  `commit` support, every message stamped on the shared `perf_counter_ns` clock).
- Timbre client (REST and WebSocket) with time-to-first-audio measurement; TTS disk cache.
- Credit protection: `data/cache/usage.jsonl` log for every API call, STT/TTS caches keyed by
  hash of audio/text + config, `--yes` gate for jobs above 50 calls.
- 13 unit tests pass, including the Prisma client against a local fake server.

**Not done yet / blocked**
- The spikes have not run against the real API: **waiting for `GNANI_API_KEY` in `.env`.**
- `docs/DECISIONS.md` D5 (commit vs fallback mode) is decided after the spike.

**Open questions**
- Is `prisma-v3.0` available on programme credits?
- What is the account's concurrency limit (1 active request)?
