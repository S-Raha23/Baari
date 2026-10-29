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
