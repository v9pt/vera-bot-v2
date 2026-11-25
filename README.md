# Vera Bot v2

Deployed at: https://vera-ai-challenge-0das.onrender.com (redeploy after this rewrite)

## Problem

The judge pushes category, merchant, customer and trigger context, then calls `/v1/tick` and expects WhatsApp-ready messages that are specific, in the right voice for the category and the merchant, tied to the trigger, and worth replying to. It then plays the merchant on `/v1/reply`. Invented facts cost points.

## Pipeline

```
/v1/context ─► Store (versioned, in memory)
/v1/tick    ─► choose() ─► resolve() ─► build_facts() ─► composer[kind] ─► validate ─► (optional polish) ─► actions
/v1/reply   ─► classify() ─► state machine ─► send | wait | end
```

| Module | Job |
|---|---|
| `vera/store.py` | Contexts per scope, versions keyed by `(scope, id)`, conversations, sent suppression keys |
| `vera/facts.py` | Resolves trigger → merchant, category, customer, digest item; flattens everything into a fact-sheet of display strings |
| `vera/grounding.py` | Extracts numbers, dates and times from a body and checks each one against the fact-sheet |
| `vera/select.py` | One merchant-scope trigger per merchant (urgency, then kind priority), customer sends kept separately, cap 20 |
| `vera/compose_merchant.py`, `compose_customer.py` | One rule composer per seed trigger kind (19 merchant, 5 customer) |
| `vera/compose.py` | Dispatch, validation, generic fallback for unseen kinds; never raises |
| `vera/polish.py` | Optional Gemini → Groq rewrite, accepted only if it passes the validator |
| `vera/reply.py` | Reply classifier (English and Hinglish) and conversation rules |

## Why rule-first

- **Grounding is checked by code.** Every number, date and time in a body must appear in the fact-sheet. `scripts/grounding_lint.py` enforces this on all 25 seed triggers.
- **Determinism.** The same input gives the same output: no randomness, no wall clock in message text, ~3 ms per tick.
- **No dependency on keys or network.** Every message is complete without the LLM; polish is an optional layer on top.
- **Voice is explicit.** Dentists are addressed as "Dr. <first name>" in a clinical, peer-to-peer tone. Salons are warm, restaurants talk operator to operator, gyms coach, pharmacies are precise. Hinglish is used when Hindi is one of the merchant's first two languages. Taboo words from each category's `voice.vocab_taboo` are blocked.
- **One signal and one CTA per message.** The CTA is always `Reply 1 to …, or 2 to …` or a single closing question.

## Optional LLM polish

Set `LLM_POLISH=1` and `GEMINI_API_KEY` or `GROQ_API_KEY` to turn it on. The model is told to keep every fact and the CTA unchanged. Its rewrite is rejected, and the rule draft ships instead, if any of these hold:

- it adds an ungrounded number or date
- it uses a taboo word
- it changes the CTA sentence or adds a second "Reply"
- it is more than 1.4× the original length
- it changes the salutation
- it introduces "Vera" or "magicpin"

Calls run in parallel under the tick deadline. Any draft still unfinished at the deadline ships as the rule body. Results are cached per trigger and context version.

## Reply policy

| Merchant says | Bot does |
|---|---|
| Auto-reply (canned text; also counted per merchant, because conversation ids can rotate) | 1st: one nudge for the owner, 2nd: wait 1800 s, 3rd: end |
| Hostile ("stop", "spam", "band karo", "mat bhejo") | end, and the conversation stays closed |
| Commit ("ok lets do it", "haan kar do", "theek hai", "1") | action mode: "Done — drafting …. Next: …", with no qualifying questions |
| Objection ("too expensive", "baad mein", "time nahi") | one reframe using a merchant fact; waits if the objection repeats |
| Question | answered from facts (views, calls, CTR, plan, offer) if possible; otherwise steers back with one CTA |
| "2" (the offered second option) | acts on that option, or backs off if it was skip/later, or ends if it was pause |
| Customer conversations | books the chosen slot label from the trigger; never uses the merchant's salutation or metrics |
| Anything else | wait |

## Deliberate deviations from the plan

- **Expiry.** The judge always sends `now` as the real clock, and the seed `expires_at` values are Apr–May 2026. Triggers the caller names in `available_triggers` are therefore never expired. Expiry against the payload `now` applies only when the bot collects triggers itself (a tick with no ids). The server clock is never used.
- **Hinglish.** Hinglish is used only when `hi` is among the merchant's first two languages and the category voice is not English-primary. A Chennai studio listing `en, ta, hi` and the gyms category both get English.
- **Suppression** is keyed by merchant, customer and `suppression_key`, because some seed keys are category-wide (`research:dentists:2026-W17`) and would otherwise block other merchants.
- **A merchant-only tick** whose triggers have all expired falls back to a single check-in message.
- **Status codes.** A stale version returns 409; the plan named only 400 and 413. `/` is kept as an info route, and `/v1/metadata` no longer sends `submitted_at` (it was wall-clock).
- **First auto-reply** gets one nudge for the owner. The local judge prints this as WARN; it still ends by turn 3.

## Limits

- All state is in memory, so a restart loses contexts and suppression keys. Call `POST /v1/teardown` or restart the server between judge runs, or the second run returns no actions.
- Hidden trigger kinds fall back to the generic composer. Its message is grounded but less specific.
- There is no LLM in the reply path.

## Run

```bash
pip install -r requirements.txt
pytest -q                       # 268 tests, no network
python scripts/grounding_lint.py
uvicorn app:app --port 8080
python judge_simulator.py       # needs GROQ_API_KEY or GEMINI_API_KEY in .env for the judge's scorer only
```

Env vars (see `.env.example`): `LLM_POLISH` (default `0`), `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-2.5-flash`), `GROQ_API_KEY`, `GROQ_MODEL` (default `openai/gpt-oss-120b`; Groq retired `llama-3.3-70b-versatile`). The judge reads the same `.env`.

## Endpoints

`POST /v1/context`, `POST /v1/tick`, `POST /v1/reply`, `GET /v1/healthz`, `GET /v1/metadata`, `POST /v1/teardown`. Status codes: 400 for an invalid scope, 409 for a stale version, 413 for a body over 500 KB.

## Render keep-alive

The free tier sleeps after inactivity, and a cold start can outlast the judge's patience. Ping `GET /v1/healthz` every 10 minutes from a free cron service (cron-job.org, UptimeRobot).

## Judge results (local)

| Scenario | Result |
|---|---|
| warmup, context push | PASS |
| auto_reply_hell | send → wait → end (ends on turn 3) |
| intent_transition | PASS (action mode) |
| hostile | PASS (end) |
| tick_scoring | 2 actions for the first 3 triggers (trg_001 and trg_002 share a merchant) |

### LLM scores

Groq retired the judge's hard-coded `llama-3.3-70b-versatile` (it returned 404), so `judge_simulator.py` now reads `GROQ_MODEL`, defaulting to `openai/gpt-oss-120b`. These numbers are therefore not directly comparable to scores from the original judge model. Polish was off (`LLM_POLISH=0`) for every run, so the scores are for the rule composers alone.

| Run | Messages | Avg /50 | Specificity | Category fit | Merchant fit | Decision quality | Engagement |
|---|---|---|---|---|---|---|---|
| `full_evaluation`, baseline | 19 | 39.0 | 7.74 | 7.79 | 7.74 | 8.32 | 7.42 |
| `full_evaluation`, after tuning (run 1) | 19 | 40.3 | 8.16 | 8.26 | 8.05 | 8.16 | 7.63 |
| `full_evaluation`, after tuning (run 2) | 19 | 41.3 | 8.42 | 8.26 | 8.42 | 8.47 | 7.68 |
| one tick per trigger, all 25 (after adding 30-day views to planning drafts) | 25 | 40.8 | 8.20 | 8.40 | 8.16 | 8.40 | 7.68 |

`full_evaluation` ticks 5 triggers at a time, and the bot sends one merchant-scope message per merchant per tick, so only 19 of the 25 are scored. The last row ticks each trigger alone (lowest 37, `milestone_reached`; highest 43). The same body varies by about ±3 points between runs, so treat a change under about 1 point in an average as noise.

**What the tuning changed.** The judge sees only part of the context: owner, locality, languages, 30-day views, calls and CTR, `signals`, active offer titles, the trigger payload, and the customer's identity. Real facts from outside that window (`customer_aggregate` counts, review quotes, 7-day deltas) were marked "fabricated" and cost about 2 points each. Composers now prefer facts the judge can see:

- `supply_alert` no longer quotes the chronic-Rx count.
- `competitor_opened` leads with the active offer and 30-day views; a review quote is used only when there is no offer.
- `dormant_with_vera` uses 30-day views against calls instead of the 7-day delta.

The other changes:

- `ipl_match_today` names the locality and explains why a weekday offer doesn't cover a weekend match.
- Gym messages use coaching lines.
- Customer messages name the owner ("Karthik from PowerHouse Fitness").
- When no customer context was pushed (the judge never pushes one), customer messages use the merchant's language rule.

This tuning targets the local judge's narrow context window. The real judge may see the full context, in which case the facts that were dropped would have been fine. Engagement is still the lowest dimension, at about 7.7. The judge asks for social proof, but peer numbers aren't in its view and would read as fabricated.
