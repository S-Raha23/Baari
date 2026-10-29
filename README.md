# Baari (बारी) — knows when it's your turn

A turn-taking engine for Indian-language voice agents. Every ~100 ms during a call Baari decides
whether the caller has finished their turn or is only pausing mid-thought, and whether a sound
made while the bot is speaking is a real interruption, a backchannel ("haan haan") or noise.
It combines local audio analysis with words from **Gnani Prisma** streaming STT; the demo agent
speaks with **Gnani Timbre** TTS.

Status: under construction. See `SPEC.md` for the design and `docs/PROGRESS.md` for status.
Results will be in `reports/RESULTS.md`, generated from recorded data.

## Setup (Windows, PowerShell)

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env    # then put your Gnani key in .env as GNANI_API_KEY
.venv\Scripts\python -m pytest
.venv\Scripts\python -m baari --help
```
