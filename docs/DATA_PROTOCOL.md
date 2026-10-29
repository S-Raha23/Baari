# Data protocol — recording sessions for Baari

Baari's results are only as good as its recordings. This document is for the **human**:
what to record, with whom, and how. Claude Code builds the tool (`python -m baari collect`);
you run the sessions.

## Rules (from the challenge terms and India's DPDP Act — voice is personal data)

- Record only yourself and people who give consent on the recording itself (the tool reads the
  consent statement aloud and records their "haan, main agree karta/karti hoon").
- Never use real phone numbers, account numbers, Aadhaar, PAN, addresses or real calls.
  Prompt cards contain generated fake values.
- Raw audio stays on your laptop (`data/raw/`, gitignored). Nothing personal goes to GitHub.
- Anyone can ask to be deleted later: `python -m baari delete-speaker --speaker S03`.

### Consent statement (read by the tool, participant answers aloud)

> "Yeh recording Baari project ke liye hai, jo voice bots ko behtar banane ke liye hai.
> Aapki awaaz sirf is project ki research ke liye use hogi, public nahi ki jayegi, aur aap
> kabhi bhi delete karwa sakte hain. Kya aap agree karte hain?"

## Who to record

- Target **at least 6 speakers**, more is better. Mix: different ages (include at least one
  person 50+), genders, and Hindi/Hinglish fluency. One regional-language speaker is a bonus.
- Each speaker gets an ID (S01, S02…). Store only: ID, age band, gender (optional), languages
  spoken, device used. No names in metadata.

## Session type A — Turns (~15 minutes per speaker)

The bot (Timbre voice) asks a question. The participant reads a **card that describes the
situation, not the exact words**, then answers in their own words, naturally. When they have
finished, they click **Done** (only after they have stopped speaking).

Instructions to say to the participant:
- "Normal phone call ki tarah bolo. Sochne ke liye ruk sakte ho, 'matlab', 'toh' bol sakte ho —
  bilkul theek hai. Jab poori baat ho jaaye, tab Done dabana."
- Don't rush them and don't coach them to pause. Natural behaviour is the data.

Target per speaker: **≥ 40 answers** across these card types (the tool rotates them):

| Card type | Example card (participant reads this) |
|---|---|
| Complaint (free text) | "Last month your EMI was deducted twice. Explain the problem." |
| Explanation | "Your card was declined at a petrol pump yesterday. Describe what happened." |
| Number slot | "Tell the bot this mobile number: 98XXX 4X1X7" (tool generates fake numbers; read it the way you normally would, in groups) |
| Date / amount | "The extra deduction was ₹4,850 on 3rd October. Tell the bot." |
| Yes / no | Bot: "Kya aap apna card block karna chahte hain?" Card: "Yes, but you're a little unsure." |
| Choice | Bot offers two options. Card: "Pick the second one, but ask a question first." |
| Emotional | "You are frustrated — this is the third time you are calling." |

## Session type B — Barge-in (~5 minutes per speaker)

The bot speaks a long explanation (15–25 s). A card tells the participant what to do
**while the bot is talking**:

| Action | Card |
|---|---|
| Backchannel | "Say 'haan haan' or 'achha' once, like you're listening." |
| Interrupt | "Interrupt: 'ruko ruko, main woh nahi pooch raha'." (or their own words) |
| Interrupt (polite) | "Interrupt politely: 'ek minute, suniye…'." |
| Silent | "Just listen." |
| Noise | "Cough once." / "Turn the TV or fan on near the mic." |

Target per speaker: **≥ 20 barge-in trials**, roughly balanced across actions.
Use **headphones** so the bot's voice doesn't leak into the microphone.

## Recording conditions

Spread each speaker's sessions across conditions; the tool records which one was used:
- quiet room, laptop mic
- fan / TV / kitchen noise in the background
- phone earphone mic (if available)
Telephone-quality versions are created later in software; don't try to record over a real call.

Also record **2–3 minutes of each noise on its own** (no speech) — used for augmentation.

## Optional — role-play pairs

Two people, two separate microphones (e.g. two phones recording close to each speaker),
role-playing caller and agent for 5 minutes using a scenario sheet. Gives natural turn changes.
Sync the two recordings with a clap at the start; the tool aligns them.

## Rough totals to aim for

| Item | Minimum | Good |
|---|---|---|
| Speakers | 6 | 10+ |
| Turn answers | 240 | 500+ |
| Pauses (auto-detected) | ~700 | 1,500+ |
| Barge-in trials | 120 | 250+ |

More speakers beats more minutes from the same speaker — the headline result is
speaker-independent.

## After recording

1. `python -m baari label` — automatic HOLD/SHIFT and barge-in labels.
2. `python -m baari audit-labels` — listen to 30 random pauses and mark any wrong label.
   Write the error rate in `docs/PROGRESS.md`. Fix systematic problems before training.
3. `python -m baari transcribe-cache` — streams every session through Prisma once (uses credits;
   the tool estimates usage and asks before starting).
