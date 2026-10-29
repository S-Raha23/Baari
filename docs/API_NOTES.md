# Gnani API notes

What we verified about the Gnani APIs, and where. Doc pages read on 30 Oct 2026 from
`https://docs.gnani.ai/llms.txt` (pages fetched as `.md`). Measured numbers live in the
generated spike reports, not here:

- `reports/spikes/stt_spike.md` — `python -m baari spike-stt`
- `reports/spikes/tts_spike.md` — `python -m baari spike-tts`

## Authentication and limits (`api/introduction/errors.md`, `api/STT/limits.md`)

- Header `X-API-Key-ID` (STT docs spell it `x-api-key-id`; headers are case-insensitive).
- `401 MISSING_API_KEY` / `INVALID_API_KEY`; `402` = insufficient credit.
- `429 RATE_LIMITED`, no `Retry-After`. Example message: *"Only 1 active request is allowed at a
  time"* — some accounts allow **one concurrent request**. Baari therefore makes API calls
  strictly sequentially (spikes, `transcribe-cache`, TTS cache warm-up). Retry 429/5xx with
  backoff (0.5 s, 1 s, 2 s).
- The account's real rate and concurrency limits are shown at app.gnani.ai (not in the docs).

## Prisma streaming STT (`api/STT/stt-websocket.md`, `api/STT/models/prisma-v3.md`)

Matches SPEC.md §3.1. Additional details:

- `wss://api.vachana.ai/stt/v3/stream`; with websockets ≥ 13 pass headers via `additional_headers`.
- Header names are now `language_code`, `model`, `format` (old `lang_code`, `x-model`,
  `x-format` still accepted).
- An unknown `model` value is **silently ignored** (falls back to v2.5, no error). Check that
  the `connected` message carries `request_id` / `config.language_code` (v3.0-only fields) to
  confirm v3.0 is really active.
- v3.0 with a single `hi-IN`/`en-IN` and no `format` returns digits — always send `format`.
- `x-min-silence-ms` range 100–2000; `x-min-speech-ms` 50–2000 (default 200 at 8 kHz);
  `x-min-segment-ms` 100–1000 (too high silently drops short answers like "haan").
- Messages: `connected` (`config.sample_rate`, `chunk_size`, v3: `request_id`,
  `language_candidates`), `speech_start` (v3: `utterance_id`), `processing`, `transcript`
  (`text`, `audio_duration_ms`, `segment_id`, `segment_index` (1-based), `latency` ms,
  `utterance_id`, `is_final` (always true), v3: `detected_language_code`), `error`,
  `settings_updated`.
- `{"type":"commit"}` "closes the open utterance immediately instead of waiting for silence.
  Works on every model."
- `update_settings` can change `language_code`, `format`, bias/keyterms and substitution, but
  **not** VAD settings (rejected) — VAD headers are fixed per connection.
- The docs say an audio stream that ends mid-speech is not finalised; end clips with ~1 s of
  silence (the spike clip ends with 2.5 s).
- Errors: bad header → `error` then close 1008; session > 15 min → `error` then close 1001;
  concurrency cap → `error` naming the limit.

## Timbre TTS (`api/TTS/tts-inference.md`, `tts-sse.md`, `tts-websocket.md`, `available-voices.md`)

- REST `POST https://api.vachana.ai/api/v1/tts/inference` → binary audio in the requested container.
- SSE `POST https://api.vachana.ai/api/v1/tts/sse`.
- WebSocket `wss://api.vachana.ai/api/v1/tts`, header `X-API-Key-ID`. Client sends one JSON
  request; server sends `{"type":"start"}`, then `{"type":"audio","data":{"chunk_index",
  "audio": <base64>, "is_final": false}}` messages, then `{"type":"complete", ...}`.
  **Audio comes as base64 inside JSON text frames, not binary frames** (SPEC.md §3.2 said
  "binary PCM chunks"). One request at a time per connection.
- Request body (all transports):

  ```json
  {"text": "...", "voice": "Poorvi", "model": "timbre-v2.5", "language": "hi-en", "speed": 1.0,
   "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2,
                    "encoding": "linear_pcm", "container": "raw"}}
  ```

  `sample_rate` ∈ {8000, 16000, 22050, 24000, 44100, 48000} (default 48000); `container` ∈
  {wav (default), raw, mp3, ogg, mulaw, alaw}; `speed` 0.85–1.15.
- `language` values: `auto`, `hi-IN`, `en-IN`, … and **`hi-en` (Hinglish, code-mixed)**.
- Models: `timbre-v2.5` (42 voices, one preferred language each) and `timbre-v3.0` (13 voices,
  all 10 languages, inline audio tags like `<pauses>`). Voices are not shared between models.
- **Hinglish voice: `Poorvi`** (timbre-v2.5, `hi-en`, female, conversational) — Baari's
  default. v3.0 examples: `Shivani`, `Avinash`, `Lakshmi`.
- Pass numbers, dates and currency as spoken words (see `tts-input-formating.md`); the agent's
  templates must spell out fake mobile numbers digit by digit.
- Baari's client strips a WAV header if one arrives despite `container=raw` (defensive).

## To verify in the spikes (needs the API key)

- [ ] `prisma-v3.0` is available on the programme credits (else fall back to v2.5 + `hi-IN`).
- [ ] `commit` closes a segment and how fast the transcript arrives (vs fallback mode).
- [ ] Whether `codemix` output for Hinglish looks right.
- [ ] Timbre first-audio latency, REST vs WebSocket; whether `container=raw` returns bare PCM.
