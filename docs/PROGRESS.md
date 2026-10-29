# Progress

## M1 — Audio + local VAD + live pause events (code done, 30 Oct 2026; live check pending)

**Works**
- `audio/capture.py`: 16 kHz mono int16, 512-sample blocks, shared-clock stamps, ring buffer,
  overflow counter. Laptop mic check: 94 blocks in 3 s, 0 overflows.
- `vad/silero.py`: Silero VAD v5 (ONNX, CPU, 0.25 ms/frame median) + `PauseTracker` with
  hysteresis emitting `speech_start`, `silence_start` (≤ 96 ms after onset), `silence_cancel`,
  `pause_start` (150 ms), all with back-dated onsets (D8).
- `audio/telephony.py`: 8 kHz round-trip, 300–3400 Hz band-pass, noise at a target SNR.
- `python -m baari listen [--wav F] [--phone --snr DB]`: live/offline event printout. On the
  synthetic Timbre spike clip it finds the 3 phrases and their pauses, clean and at 10 dB SNR
  telephone quality.
- 21 tests pass.

**Pending (needs the human)**
- Acceptance check: say "haan… matlab… theek hai" into `python -m baari listen` and confirm three
  segments with two pauses. Bundled with the M2 pilot session to save a round-trip.

## M0 — Setup and API spike (done, 30 Oct 2026)

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
- Both spikes ran against the real API. Prisma v3.0 works with `hi-IN` + `codemix`; commit
  mode chosen (D5): median text arrival 540 ms after pause onset vs 753 ms in fallback mode.
  Timbre WebSocket first audio ≈ 0.8–1.0 s. Details: `reports/spikes/`, `docs/API_NOTES.md`.
- API use so far (`python -m baari usage`): 12 Prisma sessions (47 s audio), 9 Timbre calls.

**Doesn't work / surprises**
- Prisma rejects language lists (`hi-IN,en-IN`); no `processing` messages are sent.
- Timbre REST first byte is slow (1.2–3.6 s); only WebSocket is usable live.

**Open questions**
- Real-speech word-lane timing (M3) may differ from the synthetic-clip numbers.
- Account concurrency limit not yet known (calls are kept sequential).
