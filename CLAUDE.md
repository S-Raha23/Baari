# CLAUDE.md — Baari

You are building **Baari** (बारी, "turn"): a turn-taking engine for Indian-language voice agents.
Tagline: *Knows when it's your turn.*

Read `SPEC.md` fully before writing any code. It is the source of truth for architecture,
interfaces, metrics and the build sequence. `docs/DATA_PROTOCOL.md` describes the recording
sessions the human must run; you build the tools for them.

## What Baari does (one paragraph)

Every ~100 ms during a call, Baari answers two questions: (1) has the caller finished their
turn, or are they just pausing mid-thought? (2) while the bot is speaking, is a sound from the
caller a real interruption, a backchannel ("haan haan"), or noise? It combines local audio
analysis (voice activity, pitch, energy, timing) with words from **Gnani Prisma** streaming STT,
and the demo agent speaks with **Gnani Timbre** TTS. The core deliverable is a measured result:
Baari interrupts callers less than a silence timer at the same (or lower) response delay.

## Hard rules

1. **Never fake results.** Every number in any report, README, chart or demo caption must be
   produced by code from recorded data, and the script that produced it must be committed.
   If a result is bad, report it as bad. Never hard-code, hand-edit or "illustrate" metrics.
2. **Synthetic / consented data only.** Audio may only come from the repo owner and people who
   have given recorded consent (see DATA_PROTOCOL.md). Never use real phone numbers, account
   numbers, Aadhaar, PAN or real customer calls. Generate fake numbers for prompt cards.
3. **Never commit audio or secrets.** `data/raw/`, `data/cache/`, `*.wav`, `*.pcm`, `.env`
   must be in `.gitignore` from the first commit. The API key lives in `.env` as `GNANI_API_KEY`.
4. **Protect API credits** (5,000 programme credits, no refills assumed). Cache every Prisma
   transcript and every Timbre synthesis on disk keyed by a hash of (audio or text + config).
   Offline experiments must run entirely from cache. Log credit-consuming calls to
   `data/cache/usage.jsonl` (timestamp, endpoint, seconds of audio / characters). Ask the human
   before any job that would make more than ~50 API calls.
5. **Verify APIs, don't guess.** Gnani's docs index is `https://docs.gnani.ai/llms.txt` and
   pages are available as `.md`. When a request/response field is not stated in SPEC.md, read
   the docs or test it in a spike, then record what you learned in `docs/API_NOTES.md`.
6. **No LLM in the real-time decision path.** The turn model must be a small, fast model
   (LightGBM first). Evon is optional and only for offline work or reply generation.
7. **Respect the target machine**: Windows laptop, AMD Ryzen 7 8840HS, 24 GB RAM, integrated
   Radeon 780M, **no CUDA**. Everything must run on CPU. Prefer ONNX Runtime for neural parts.

## Environment

- Python 3.11, virtual environment in `.venv`, dependencies pinned in `pyproject.toml`.
- Use `sounddevice` for mic/speaker I/O, `websockets` for Prisma/Timbre, `onnxruntime` +
  Silero VAD for local VAD, `numpy`/`scipy`/`librosa` for features, `lightgbm` + `scikit-learn`
  for the model, `fastapi` + `uvicorn` for the demo server, `matplotlib` for report plots.
- Commands must work in PowerShell. Avoid bash-only syntax in scripts and docs.
- Provide a single entry CLI: `python -m baari <command>` (see SPEC.md §11).

## How to work

- Build in the milestone order in SPEC.md §13. Each milestone has acceptance criteria; meet them
  before moving on. At the end of each milestone: run tests, update `docs/PROGRESS.md`
  (what works, what doesn't, open questions), and make one git commit with a clear message.
- When a milestone needs the human (recording sessions, getting an API key, accepting the
  Hugging Face licence), stop and tell them exactly what to do, how long it takes, and which
  command to run. Do not invent stand-in data to skip the step.
- Write tests for pure logic (feature extraction, labelling, metrics, policies). Use small
  fixture WAVs that the code generates synthetically (sine tones + silence), never personal audio.
- Keep modules small and typed. Every module has a docstring explaining its role in the pipeline.
- When you hit a design decision not covered by SPEC.md, choose the simplest option that keeps
  the evaluation honest, write the decision in `docs/DECISIONS.md`, and continue.
- Keep a single monotonic clock (`time.perf_counter_ns`) for all event timestamps so latency
  measurements are trustworthy.

## Definition of done (whole project)

See SPEC.md §14. In short: live demo works on the laptop, `reports/RESULTS.md` is generated from
real recordings with leave-one-speaker-out evaluation, the README explains the result and its
limits honestly, and side-by-side demo clips exist for the 60-second video.
