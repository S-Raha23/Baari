# Baari — Technical Specification

**Baari** (बारी, "turn") is a turn-taking engine for Indian-language voice agents. It decides,
every ~100 ms, whether the caller has finished their turn and whether a sound made while the bot
is speaking is a real interruption. It uses **Gnani Prisma** (streaming speech-to-text) for words,
local audio analysis for timing and prosody, and **Gnani Timbre** (text-to-speech) for the demo
agent's voice. **Gnani Evon** is optional (offline scripting / reply generation).

Built for the Great Indian AI Internship Challenge (Gnani AI). Deadline: 10 Nov 2026, 23:59 IST.

---

## 1. Problem

Voice bots decide when to reply with a silence timer: "if the caller has been quiet for X ms, reply".

- X short (≈500 ms) → the bot interrupts people who pause mid-thought.
- X long (≈1500 ms) → every reply starts after an awkward dead pause.

Hindi and Hinglish speakers pause mid-sentence constantly ("mera loan ka EMI… matlab pichle
mahine ka… 2 baar kat gaya"). A single silence threshold cannot separate a *thinking pause* from
an *end of turn*. Elderly and less fluent speakers are hit hardest.

The same problem exists in reverse while the bot is talking: "haan haan" (go on), "ruko ruko"
(stop), a cough and a TV in the background all look like "user speech" to a naive bot.

## 2. Goals and non-goals

**Goals**
- G1. An end-of-turn model whose cut-in-rate vs response-delay curve beats fixed silence timers
  on held-out speakers (leave-one-speaker-out).
- G2. Barge-in handling that separates interruption / backchannel / noise, stops fast on real
  interruptions and remembers what the caller actually heard.
- G3. A live demo agent (Hinglish bank-support scenario) on the laptop, with a dashboard that
  shows Baari's decisions next to a silence-timer baseline in real time.
- G4. A reproducible evaluation report generated from real consented recordings.
- G5. Runs entirely on the target laptop CPU (Ryzen 7 8840HS, 24 GB RAM, no CUDA, Windows).

**Non-goals**
- Training a speech recogniser or TTS. Replacing Prisma's VAD (Baari sits on top of it).
- Real telephony (SIP/PSTN). Telephone conditions are *simulated* (8 kHz + band-pass + noise).
- Production deployment, multi-user scaling, authentication.

## 3. Gnani API facts (verified from docs on 29 Oct 2026 — re-verify in M0)

Docs index: `https://docs.gnani.ai/llms.txt` (pages also available as `.md`). Base host: `api.vachana.ai`.

### 3.1 Prisma streaming STT
- Endpoint: `wss://api.vachana.ai/stt/v3/stream`. All config via WebSocket upgrade headers.
- Headers: `x-api-key-id` (required), `language_code` (required; Prisma v3.0 accepts a list of
  1–4 like `hi-IN,en-IN`, or `indic-auto`), `model` (`prisma-v3.0` or `prisma-v2.5`, default
  v2.5), `format` (`verbatim` | `transcribe`; v3.0 also `codemix` | `transliterate`),
  `x-sample-rate` (8000/16000/44100/48000), `previous_text` (v3.0 context), `x-idle-timeout-sec`.
- VAD headers (fixed per connection): `x-vad-threshold` (0–1, default 0.7),
  `x-min-silence-ms` (100–2000, default 500), `x-min-speech-ms` (default 100),
  `x-min-segment-ms` (default 120), `x-max-speech-s` (optional).
- Audio: raw PCM signed 16-bit little-endian mono, **exactly 1,024-byte frames** (512 samples),
  sent at **real-time cadence** (one frame per 32 ms at 16 kHz). Do not burst.
- Server messages (JSON, `type` field): `connected`, `speech_start`, `processing` (VAD closed a
  segment, transcription started), `transcript` (final text for one segment: `text`,
  `audio_duration_ms`, `segment_index`, `latency` ms, `utterance_id`, `is_final`), `error`,
  `settings_updated`.
- **There are no interim/partial transcripts.** Text arrives only when a segment closes.
- Client control frames (JSON text): `{"type":"commit"}` closes the open utterance immediately
  instead of waiting for silence; `{"type":"update_settings", ...}` changes language/format/bias.
- Limits: 15-minute session cap (then close 1001); idle timeout default 60 s; per-org
  concurrency cap. Browser WebSockets cannot set headers → the backend must hold the connection.
- Python SDK `gnani-vachana` exists but does **not** expose VAD headers → use raw `websockets`.

### 3.2 Timbre TTS
- REST: `POST https://api.vachana.ai/api/v1/tts/inference` (returns full audio).
- SSE streaming: `POST https://api.vachana.ai/api/v1/tts/sse`.
- WebSocket: `wss://api.vachana.ai/api/v1/tts` (streams binary PCM chunks, lowest latency).
- Request fields, voice names, sample rate and language parameters: **read the TTS docs in M0**
  and record them in `docs/API_NOTES.md`.

### 3.3 Evon v3.3 (optional)
- Open weights only (not on the API): Hugging Face `gnani/gnani-evon-v3.3-30B-A3B`, gated
  (accept conditions first). ~30B params, ~3.5B active per token, 128K context.
- On this laptop it only runs heavily quantised (≈3–4-bit GGUF via llama.cpp, CPU) at a few
  tokens/s. Never in the real-time path. Uses: generating prompt-card variety offline, and an
  optional free-form reply mode for the agent with speculative pre-generation (§6.6).

## 4. Core design insight

Prisma's VAD tells you **a pause happened**. Baari decides **whether the pause matters**.

Because Prisma returns text only when a segment closes, Baari works on two time scales:

```
mic ──► 16 kHz frames (32 ms) ──┬──► LOCAL LANE (every frame, ~0 ms delay)
                                │      Silero VAD → pause onset
                                │      prosody: pitch slope, energy decay, final lengthening
                                │
                                └──► WORD LANE (Prisma stream)
                                       on local pause ≥ C ms → send {"type":"commit"}
                                       → Prisma transcribes the segment → text arrives
                                         ~latency ms later (measure it)

           every 100 ms of pause:  features(local lane + words so far + dialogue context)
                                       → turn model → p_end(t)
                                       → policy: wait | prepare reply | respond
```

- C (commit delay) starts at ~120 ms and is tuned in evaluation.
- Some pauses can be decided from the local lane + context alone (e.g. a short falling "haan"
  after a yes/no question). Most need the word lane (Hindi is verb-final: a segment ending in a
  verb like "kat gaya" / "hai" / "chahiye" is strong end-of-turn evidence; a segment ending in
  "matlab" / "toh" / "aur" / a noun is strong continuation evidence).
- **Fallback mode** if `commit` turns out unreliable: don't commit; set `x-min-silence-ms` to
  150–250 so Prisma closes a segment at every pause. M0 decides which mode to use, by measurement.

## 5. Terms

- **Segment**: speech between two local-VAD silences ≥ `PAUSE_MIN_MS` (default 150 ms).
- **Pause**: a silence ≥ `PAUSE_MIN_MS` after a segment.
- **Turn**: everything a speaker says before the other side should respond.
- **HOLD pause**: a pause after which the same speaker continues. **SHIFT pause**: the final pause of a turn.
- **Tick**: a decision point inside a pause, every 100 ms from pause onset (100, 200, …, 2000 ms).
- **Cut-in**: the system decides to respond during a HOLD pause.
- **Response delay**: time from true turn end (start of SHIFT pause) to the system's decision.

## 6. Components

### 6.1 Audio I/O (`baari/audio/`)
- Capture with `sounddevice` at 16 kHz mono int16, 512-sample blocks; ring buffer; every block
  stamped with `time.perf_counter_ns` (single clock for the whole system).
- Playback of TTS audio with: position tracking (which text chunk is playing), **ducking**
  (instant volume drop) and **stop**.
- Telephone simulation (`telephony.py`): resample to 8 kHz and back, 300–3400 Hz band-pass,
  additive noise at a given SNR from noise clips (fan, TV, street, babble) recorded by the human
  or from a licence-compatible noise set; record the licence in `docs/DECISIONS.md`.

### 6.2 Local VAD (`baari/vad/`)
- Silero VAD via ONNX Runtime on CPU. Emits `speech_start`, `speech_end` events with timestamps
  and per-frame speech probability. Hysteresis to avoid flicker.

### 6.3 Prisma client (`baari/stt/`)
- Raw `websockets` client with the headers in §3.1. Real-time pacing of 1,024-byte frames.
- Sends `commit` on local pause ≥ C ms (commit mode) or relies on Prisma VAD (fallback mode).
- Aligns each returned transcript to its local segment (by order and timing) and records
  `prisma_latency_ms` and `text_arrival_ms` (relative to pause onset).
- Reconnects proactively before the 15-minute cap; handles `error` messages.
- **Cache**: for offline experiments, transcripts are stored per recording + config hash in
  `data/cache/stt/`; re-running evaluation never calls the API again.
- Default config: `model=prisma-v3.0`, `language_code=hi-IN,en-IN`, `format=codemix`
  (fall back to v2.5 + `hi-IN` if v3.0 is not available on the programme credits).

### 6.4 Features (`baari/features/`)
Computed at every tick; each feature must be computable from information available **at that
tick** (no peeking at the future). Mark text features missing (NaN) if the segment's transcript
has not arrived yet at that tick — LightGBM handles NaN natively.

| Group | Features |
|---|---|
| Timing | ms since pause onset; current segment duration; turn duration so far; number of pauses so far in the turn; mean/median pause length of this speaker so far in the call; speaking rate (VAD-speech ms per segment) |
| Prosody (last 500 ms of speech) | pitch (F0) slope and final F0 relative to speaker's running median; F0 present/absent at end; energy slope; final syllable lengthening proxy (duration of last voiced run vs speaker median); creak/low-energy tail |
| Lexical (from Prisma text) | last token; last token class from a curated lexicon: verb-final ending (hai, tha, gaya, gayi, hoga, chahiye, karo, dijiye, hua, raha, sakta…), filler/continuation (matlab, toh, aur, woh, ki, jo, ya, means, like, so, basically, uh, um), question tag (na, haan?, kya, kyun, right), backchannel (haan, hmm, achha, ji, ok); tokens in segment; segment ends in a number; Devanagari/Latin ratio |
| Context | what the bot last asked (slot type: yes/no, number, free-text, choice); for number slots, digits captured so far vs expected length; whether the bot's last utterance was a question |

Keep the lexicon in `baari/features/lexicon_hi.yaml` so it can be extended to other languages.

### 6.5 Turn model (`baari/model/`)
- Training rows: one row per (pause, tick) for ticks 100…2000 ms while the pause is still
  ongoing. Label = 1 if the pause is a SHIFT pause, else 0.
- Model: LightGBM binary classifier + isotonic calibration on a validation fold.
- Variants for ablation: `acoustic_only`, `lexical_only`, `full`.
- Validation: **leave-one-speaker-out** cross-validation (speaker-independent). Never report
  in-speaker scores as the headline.
- Inference must run in < 5 ms per tick on the laptop CPU (measure and report).
- Export: model file in `models/` (gitignored if large) + `models/card.md` with data size,
  features, CV scores.
- Stretch (only after everything else): a tiny GRU over frame-level features exported to ONNX.

### 6.6 Endpointing policy (`baari/policy/endpoint.py`)
- At each tick: if `p_end ≥ θ_respond` → respond. If pause ≥ `T_MAX_MS` (default 2000) → respond
  anyway (safety). If `p_end ≥ θ_prepare` → start preparing the reply (speculative) so it is
  ready when the respond decision lands; discard if the caller resumes.
- θ values are chosen on validation data from the trade-off curve, not by hand.

### 6.7 Barge-in (`baari/policy/bargein.py`)
States while the bot speaks: `SPEAKING → DUCKED → (RESUMED | STOPPED)`.
- Caller speech onset ≥ 120 ms (local VAD) → **duck** playback immediately (e.g. to 25% volume).
- Classify within a short window using local features (duration, energy, pitch) and the Prisma
  transcript of that short segment when it arrives (commit at segment end):
  - backchannel ("haan", "hmm", "achha", "ji", "ok", short, low energy) → restore volume, continue;
  - interruption ("ruko", "nahi", "wait", "ek minute", "suniye", or sustained speech) → **stop**,
    record `heard_text` = text played so far, hand the turn to the caller;
  - noise (no transcript / non-speech) → restore and continue.
- Self-echo: the demo uses headphones (state this honestly in the README). Stretch: gate the mic
  by comparing it to the playback reference signal.
- Start with rules + thresholds; train a small classifier only if enough barge-in data exists.

### 6.8 Demo agent (`baari/agent/`)
- Deterministic state machine for a Hinglish bank-support call. Scenarios:
  1. "EMI do baar kat gaya" complaint (free-text turns with natural pauses).
  2. Mobile number capture (number slot, expected 10 digits — fake numbers only).
  3. Card block confirmation (yes/no slot).
  4. Long explanation from the bot (charges / refund timeline) to exercise barge-in.
- Replies are templated Hinglish strings spoken by Timbre (streaming), cached by text hash.
- Optional `--reply-mode evon`: free-form replies from local Evon, pre-generated speculatively.

### 6.9 Baselines (`baari/policy/baselines.py`)
- **B1 Silence timer**: respond after X ms of local-VAD silence, X swept 200–2000 ms.
- **B2 Prisma VAD endpointing**: respond when Prisma returns a transcript, using several
  `x-min-silence-ms` values (computed offline from cache where possible).
- Frame B2 respectfully: Prisma's VAD is a segmenter, Baari is a turn decision layer on top.

### 6.10 Live app (`baari/app/`)
- FastAPI backend owns mic, speaker, Prisma and Timbre connections; pushes events to the browser
  over a WebSocket. Single-page dashboard (plain HTML/JS, no build step), served at
  `http://localhost:8000`.
- Dashboard lanes (scrolling timeline): local VAD speech/silence; Prisma segments with text and
  arrival time; `p_end` meter with θ line; decision markers for **Baari** and for the
  **silence-timer baseline** ("would have interrupted here"); bot speech with duck/stop markers;
  live latency numbers.
- Modes: **Live** (talk to the agent) and **Replay** (feed a recorded session through both
  policies; render a side-by-side clip where each lane has its own bot voice, for the video).

### 6.11 Data collection (`baari/collect/`)
Implements DATA_PROTOCOL.md: consent capture, scenario/prompt-card display, bot prompt playback
(Timbre, cached), recording, the participant's **Done** button, per-session metadata, and
automatic labelling (§7). Output to `data/raw/<speaker_id>/<session_id>/`.

### 6.12 Evaluation (`baari/eval/`)
Replay harness that runs any policy over recorded sessions using cached transcripts with the
**recorded arrival timings** (so offline results reflect real word-lane delay). Produces metrics
(§8), plots and `reports/RESULTS.md`.

## 7. Labels

- **Turn sessions**: the bot asks; the participant answers naturally and clicks **Done** after
  finishing. Local VAD finds all pauses ≥ `PAUSE_MIN_MS` inside the answer. Every pause except
  the last = HOLD; the last pause before Done = SHIFT; true turn end = last speech offset.
- **Barge-in sessions**: the prompt card tells the participant what to do during a long bot
  utterance (backchannel / interrupt / stay silent / make a noise). Label = card action;
  onset time from local VAD.
- **Optional role-play recordings** (two people, two separate mics/channels): speaker change =
  SHIFT, same-speaker continuation = HOLD.
- Write a label-audit command that prints a sample of pauses with their transcripts and labels
  so the human can spot-check 30 of them; record the error rate found.

## 8. Evaluation

Headline (leave-one-speaker-out, bootstrap 95% CIs):
1. **Trade-off curve**: per-turn cut-in rate (% of turns with ≥ 1 cut-in) vs median response
   delay. Baari by sweeping θ_respond; B1 by sweeping X; B2 at its settings. One plot.
2. **Operating-point table**: at the θ chosen on validation, report cut-in rate, median and P90
   response delay, vs B1 at matched delay and B1 at matched cut-in rate.
3. **Ablations**: acoustic-only vs lexical-only vs full.
4. **Breakdowns**: per speaker, clean vs noisy vs simulated-telephone audio, Hindi-dominant vs
   English-dominant code-mix.
5. **Word-lane timing**: distribution of text arrival after pause onset (commit vs fallback mode).
6. **Barge-in**: stop latency (onset → playback stopped), false-stop rate on backchannels and
   noise, missed-interruption rate.
7. **Compute**: model inference time per tick; end-to-end live latency (caller stops → first bot
   audio) measured in live mode.

`reports/RESULTS.md` is fully generated by `python -m baari report`. It must include dataset size
(speakers, minutes, turns, pauses), a limitations section, and the exact config used.

## 9. Latency budget (targets to measure, not claims)

| Stage | Target |
|---|---|
| Local VAD pause onset detection | ≤ 100 ms |
| Commit delay C | ~120 ms (tuned) |
| Prisma text arrival after commit | measure (docs example shows ~300 ms) |
| Feature + model per tick | < 5 ms |
| Reply ready (speculative) | before respond decision |
| Timbre first audio after respond | measure; use WebSocket streaming |
| Barge-in duck after caller onset | ≤ 150 ms |
| Barge-in stop after interruption onset | ≤ 500 ms |

## 10. Tech stack

Python 3.11 · sounddevice · numpy · scipy · librosa (pitch via `librosa.yin`, or `pyworld` if
faster) · onnxruntime + Silero VAD · websockets · lightgbm · scikit-learn · fastapi · uvicorn ·
matplotlib · pydantic · pyyaml · python-dotenv · pytest. Optional: llama-cpp-python for Evon.

## 11. Repository layout and CLI

```
baari/
  CLAUDE.md  SPEC.md  README.md  pyproject.toml  .env.example  .gitignore
  docs/  DATA_PROTOCOL.md  API_NOTES.md  DECISIONS.md  PROGRESS.md
  src/baari/
    __main__.py          # CLI dispatcher
    config.py            # all tunables in one place (dataclass + YAML override)
    clock.py
    audio/  capture.py  playback.py  telephony.py
    vad/    silero.py
    stt/    prisma_stream.py  cache.py
    tts/    timbre.py  cache.py
    features/ timing.py  prosody.py  lexical.py  context.py  lexicon_hi.yaml
    model/  dataset.py  train.py  infer.py
    policy/ endpoint.py  bargein.py  baselines.py
    agent/  dialogue.py  scenarios.yaml
    collect/ recorder.py  consent.py  label.py  cards.yaml
    eval/   replay.py  metrics.py  plots.py  report.py
    app/    server.py  static/index.html  static/app.js
  tests/
  data/      (gitignored: raw/, cache/, processed/)
  models/    (gitignored binaries + committed card.md)
  reports/   RESULTS.md  figures/
```

CLI (`python -m baari <command>`):
`spike-stt`, `spike-tts`, `devices`, `collect --speaker S --kind turns|bargein`, `label`,
`audit-labels`, `transcribe-cache`, `train`, `eval`, `report`, `serve`, `replay --session ID`.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| `commit` slower or unreliable | Fallback mode (low `x-min-silence-ms`); decided by M0 measurement |
| Too little data | Many short sessions with several speakers; leave-one-speaker-out; report CIs; stop adding features once data is the bottleneck |
| Credits run out | Cache everything; usage log; ask before large jobs; offline eval from cache |
| Pitch unreliable in noise | Report prosody ablation per condition; model can rely on other features |
| Echo of bot voice | Headphones in demo; stated in README |
| Evon too slow | Optional; agent is deterministic by default |
| Overfitting to the author's voice | Speaker-independent CV is the headline number |

## 13. Build sequence (milestones with acceptance criteria)

**M0 — Setup and API spike**
Project skeleton, `.gitignore`, `.env.example`, CLI, tests running. `spike-stt` streams a
recorded WAV to Prisma in both commit mode and fallback mode and prints segment text,
`latency`, and text arrival relative to local pause onset. `spike-tts` synthesises one Hinglish
sentence via REST and via WebSocket and reports time to first audio. Findings in
`docs/API_NOTES.md`, mode decision in `docs/DECISIONS.md`.
*Accept*: both spikes run against the real API; numbers recorded.

**M1 — Audio + local VAD + live pause events**
Mic capture, Silero VAD, pause events printed live with timestamps; telephone simulation module.
*Accept*: speaking "haan… matlab… theek hai" prints correct segments/pauses; unit tests pass.

**M2 — Data collection tool**
Consent capture, prompt cards, bot prompts via Timbre (cached), recording, Done button,
metadata, barge-in session mode. *Accept*: the human records one 5-minute pilot session and the
files + metadata look right. **Then stop and ask the human to run the recording sessions in
DATA_PROTOCOL.md.**

**M3 — Labelling + transcript cache**
Automatic HOLD/SHIFT labels, barge-in labels, `transcribe-cache` (real-time-paced streaming of
each session through Prisma, storing text + arrival timings), `audit-labels`.
*Accept*: label audit by the human done; error rate recorded.

**M4 — Features + baselines**
All feature groups with no-future-leakage tests; B1 and B2 evaluated by the replay harness.
*Accept*: baseline trade-off curve plotted from real data.

**M5 — Turn model**
LightGBM + calibration, leave-one-speaker-out CV, ablations, θ selection, inference timing.
*Accept*: trade-off plot with Baari vs baselines; model card written.

**M6 — Live engine + barge-in**
Real-time loop: features → model → policy; speculative reply prep; barge-in state machine with
duck/stop and `heard_text`. *Accept*: live end-to-end latency and barge-in metrics measured.

**M7 — Demo agent + dashboard + replay clips**
Agent scenarios, dashboard lanes, Live and Replay modes, side-by-side clip export.
*Accept*: the human can hold a full call with the agent; at least three side-by-side clips exported.

**M8 — Report and README**
`python -m baari report` generates RESULTS.md and figures; README with problem, how it works
(include the timeline example), results, limitations, Gnani models used, how to run; draft of the
submission write-up and a 60-second video script in `docs/SUBMISSION.md`.
*Accept*: a fresh clone + `.env` + cached data reproduces the report.

## 14. Definition of done

- Live demo runs on the laptop; dashboard shows Baari vs baseline decisions in real time.
- `reports/RESULTS.md` generated from real consented recordings with speaker-independent numbers,
  CIs, ablations and limitations — no hand-entered numbers anywhere.
- Side-by-side demo clips exported for the 60-second video.
- README and `docs/SUBMISSION.md` name the Gnani models used (Prisma, Timbre, and Evon if used)
  and each team member's contribution.
- No audio, keys or personal data in the git history.
