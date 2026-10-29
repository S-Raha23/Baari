# Design decisions

Decisions not covered by SPEC.md, newest last. Each says what was chosen and why.

## D1 — M0 spike audio is synthetic Timbre speech (30 Oct 2026)

`spike-stt` needs a clip with known pauses. Instead of a personal recording it builds one from
three Hinglish phrases synthesised by Timbre (cached) joined by 700 ms and 900 ms silences.
This keeps M0 free of personal data and makes the pause onsets exactly known. A real
recording can be passed with `--wav`. TTS speech is cleaner and more fluent than real callers,
so the M0 timings are a best-case word-lane delay; M3 measures it on real recordings.

## D2 — Energy VAD for M0 pause onsets; Silero from M1 (30 Oct 2026)

M0 only needs pause onsets on a clean synthetic clip, so `baari/vad/energy.py` (causal,
−40 dBFS threshold, hysteresis) provides them. Silero VAD (SPEC §6.2) replaces it for real
audio in M1; the energy VAD stays as a dependency-free fallback and for tests.

## D3 — Spike measurement conventions (30 Oct 2026)

- Frame k is sent at t0 + (k+1)·32 ms, the moment a microphone would have delivered it, so
  "ms after pause onset" means the same thing offline and live.
- Commit mode connects with `x-min-silence-ms=2000` (the maximum) so segment closes come from
  our commits, and sends `commit` C ms after each local pause onset (C = 120 ms by default).
- Fallback mode connects with `x-min-silence-ms=200` and sends no commits.
- Each transcript is paired with the latest local pause onset at or before the `processing`
  message that preceded it, or with the transcript itself when (as observed) no `processing`
  message is sent.

## D4 — API calls are strictly sequential (30 Oct 2026)

The error docs show accounts that allow only one active request at a time (429). All batch
work (TTS cache warm-up, `transcribe-cache`) runs one call at a time.

## D5 — Commit mode is the default word-lane mode (30 Oct 2026)

Rule fixed before measuring: choose **commit mode** if every local segment gets exactly one
transcript and its median text arrival after pause onset is lower than fallback mode's;
otherwise use **fallback mode**.

Result (`reports/spikes/stt_spike.md`, 2 runs per mode, synthetic clip with 4 local pauses):
commit mode returned 4 transcripts per run (one per local segment) with median text arrival
540 ms after pause onset (C = 120 ms included); fallback mode (`x-min-silence-ms=200`)
returned 3 per run (merged "matlab" with the next phrase), median 753 ms. → **Commit mode.**
Caveat: synthetic TTS speech; re-measured on real recordings in M3 (word-lane timing, SPEC §8.5).

## D6 — Prisma language `hi-IN` + `codemix` (30 Oct 2026)

SPEC §6.3 asked for `language_code=hi-IN,en-IN`; the server rejects language lists (see
API_NOTES). `hi-IN` with `format=codemix` keeps English words in Latin script, which is what
the lexical features need for Hinglish. `indic-auto` is the alternative if regional-language
speakers are recorded.

## D7 — Timbre defaults: `timbre-v2.5`, voice `Poorvi`, language `hi-en`, 16 kHz raw PCM (30 Oct 2026)

Poorvi is the only voice documented as Hinglish. 16 kHz matches the capture pipeline, so the
bot's audio needs no resampling. The live agent uses the WebSocket transport (first audio
≈ 0.8–1.0 s vs 1.2–3.6 s for REST, `reports/spikes/tts_spike.md`).

## D8 — Provisional `silence_start` event at 64 ms (30 Oct 2026)

SPEC §5 defines a pause as silence ≥ `PAUSE_MIN_MS` (150 ms), but §9 budgets ≤ 100 ms for
pause-onset detection. The tracker therefore emits `silence_start` after 64 ms of silence
(detected 64–96 ms after the onset), `silence_cancel` if speech resumes first, and the confirmed
`pause_start` at 150 ms. All three carry the back-dated onset, so ticks are always measured from
the true speech offset. The commit (C = 120 ms) and speculative work can start from `silence_start`.

## D9 — Silero VAD v5.1.2 ONNX, downloaded on first use (30 Oct 2026)

Model: `snakers4/silero-vad` v5.1.2 `silero_vad.onnx`, **MIT licence**, SHA-256
`2623a295…bdd788f` (checked on load). Stored in `models/` (gitignored); `ensure_model()`
downloads it on a fresh clone. Inference runs single-threaded on CPU: median 0.25 ms per 32 ms
frame on the target laptop (`python -m baari listen --wav …` prints it).

## D10 — Audio time comes from the sample count, not callback timestamps (30 Oct 2026)

On the laptop's default (MME) input, blocks arrive with jitter (interval p5 29 ms, p95 40 ms,
median 30 ms over 3 s; no overflows). Event onsets are therefore computed as
block index × 32 ms (exact audio time); each block's `perf_counter_ns` stamp is kept to map
audio time onto the shared clock for cross-lane latency measurements.

## D11 — Collection UI is the terminal; ENTER is the Done button (30 Oct 2026)

The simplest option that keeps all audio in the backend: cards are shown in the console, keys
are read with `msvcrt` (ENTER = Done/continue, r = redo, s = skip, q = quit). The key-press time
is logged on the shared clock. The Done press only marks *that* the turn is over; the true turn
end is the last local-VAD speech offset before it (SPEC §7), so reaction time on the key does
not enter the labels. Keys pressed while the bot talks are discarded.

## D12 — Fake mobile numbers start with 5 (30 Oct 2026)

Indian mobile numbers start with 6–9, so a 10-digit number starting with 5 cannot belong to a
real person. Other card values (last-4 digits, 6-digit codes, amounts, dates) are random and
not linked to anything real.

## D13 — One continuous recording per session + clock fit (30 Oct 2026)

Each session is one `mic.wav`. Events (card shown, playback start/end, Done) are logged with
`perf_counter_ns`; a least-squares fit of block delivery times vs sample counts maps any event
to a sample (dry run: measured rate 16000.13 Hz, 0 overflows). Playback timestamps are when
samples were handed to the device; the device output latency (≈ 96 ms on the default MME
device) is stored per prompt so the labeller can shift to acoustic time.

## D14 — Bot prompts are synthesised sentence by sentence (30 Oct 2026)

Long barge-in explanations (19.8–24.1 s) are cached per sentence and joined with 150 ms gaps,
so the tool knows exactly which sentence was playing at any moment (`chunk_starts` in
events.jsonl) — this is what `heard_text` uses. Warm-up: `python -m baari collect --prepare-only`
(37 Timbre calls, done 30 Oct 2026).
