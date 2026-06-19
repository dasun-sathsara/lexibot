<aside>
⚠️

Preliminary plan. **Updated through a full branch-by-branch stress-test — every open dependency is now resolved (consolidated in §12).** Locked decisions are marked **[DECIDED]**. Built from web research (Jun 2026); model/SDK/API facts verified against current docs.

</aside>

## 1. Intent

A Telegram bot that lets your brother send English words throughout the day. For each word, a workflow:

1. Generates the meaning in **Sinhala + English**.
2. Generates **two example sentences**.
3. Generates **audio** for the word and the two sentences (English TTS).
4. Builds an Anki note and gets it into his **deck**, synced to his self-hosted sync server.
5. He pulls the new cards by syncing the Anki app on his phone.

## 2. Research findings (corrections to the brief)

| Topic       | Your assumption                                | Reality (Jun 2026)                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ----------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LLM         | "Gemini 3.1 Pro"                               | Real: `gemini-3.1-pro-preview`. Also `gemini-3.5-flash` (GA 2026-05-19) — faster/cheaper, strong enough for this task.                                                                                                                                                                                                                                                                                                                                |
| SDK         | "Google AI Studios SDK"                        | Use the unified **Google Gen AI SDK** (`google-genai`). The old `google-generativeai` is deprecated.                                                                                                                                                                                                                                                                                                                                                  |
| TTS         | "MAI-TTS"                                      | **MAI-Voice-2** on Azure AI Foundry (multilingual) — confirmed available in your subscription (resource `centurion-us`). Called via the Azure Speech SDK; voice-name format `<lang>-<Name>:MAI-Voice-2`. ~$22 / 1M chars.                                                                                                                                                                                                                             |
| Telegram    | "native tables + checklists"                   | **Checklists: yes** — genuinely native (Bot API 9.1, `sendChecklist`). **Tables: not a native primitive** — the clean "table" output from agent tools (e.g. Starchild) is markdown→best-effort conversion (Unicode box-drawing in monospace, or images), not a Telegram table entity. Fine for us: we mostly send words/confirmations, and use native checklists for batch "added / skipped" summaries (via a converter like `telegramify-markdown`). |
| Anki server | "run sync server, add cards, deploy to Heroku" | The **sync server only syncs** — it has no add-card API. Adding notes needs **AnkiConnect in a headless Anki desktop** or **genanki**. Heroku's ephemeral filesystem is a bad fit for Anki's stateful collection; the existing VPS is better.                                                                                                                                                                                                         |

## 3. The key architectural decision: how cards get in + synced

This is the crux. **[DECIDED — Q1] Option A (Headless Anki + AnkiConnect).** Three approaches were considered:

**Option A — Headless Anki + AnkiConnect (recommended).** Run a headless Anki desktop in Docker on the VPS with the AnkiConnect add-on. The bot calls AnkiConnect's HTTP API (`addNote`, `storeMediaFile`, then `sync`). This adds the note _and_ pushes it to the sync server, so the phone just syncs normally. Most robust for an "add a card and it shows up" flow.

**Option B — genanki `.apkg`.** Generate a `.apkg` with media and import it. Simple, but does not auto-sync into the existing deck — needs a manual import step. Poor fit for the "send word, refresh phone" UX.

**Option C — Direct collection edit.** Manipulate `collection.anki2` directly. Fragile, easy to corrupt, not recommended.

> Recommendation: **Option A**, co-located with the sync server on the VPS.

<aside>
🔑

A community Docker image like `mlcivilengineer/anki-desktop-docker:main` provides a browser-based desktop with AnkiConnect pre-installed, which we co-locate with a separate self-hosted sync server container (`chrislongros/anki-sync-server-enhanced:latest`).

</aside>

## 4. Proposed architecture (assuming Option A)

```jsx
Telegram  ──webhook──▶  Bot service (Python, aiogram)
                              │
                              ├─▶ Job queue (per-word tasks, 10-word LLM chunks)
                              │
                              ├─▶ Gemini (google-genai): meaning (Si+En) + 2 sentences
                              ├─▶ MAI-Voice-2 (Azure AI Foundry): audio for word + 2 sentences
                              │
                              └─▶ AnkiConnect (headless Anki, Docker) ─▶ self-hosted sync server
                                                                              ▲
                                                                Phone Anki app syncs ┘
```

**[DECIDED — Q2] Hosting: split by statefulness.** Heroku is fine for the _stateless_ bot, but **not** for the Anki pieces: Heroku dynos have an ephemeral filesystem that wipes on every restart/deploy (and at least daily), which would corrupt or lose Anki's collection + sync state. So:

- **Stateful (must stay on the VPS, with a persistent volume):** `anki-sync-server` + `anki-headless` (AnkiConnect).
- **Stateless (Heroku-friendly, or also on the VPS):** the `bot` + job queue, talking to AnkiConnect over HTTPS.

**[DECIDED] Everything on one VPS** via Docker Compose: `bot`, `anki-headless` (AnkiConnect), `anki-sync-server`, and a small queue/state store (Redis or SQLite). No Heroku.

### 4a. Deployment & automation (researched)

Goal: **full unattended deployment.** Proposed stack:

- **Orchestration:** one `docker-compose.yml` on the VPS; every service `restart: unless-stopped`.
- **TLS + reverse proxy:** **Caddy** — automatic TLS (Let's Encrypt) config using `handle` blocks (routing `/webhook` and `/healthz` to the bot) and reading the domain from the `.env` file via `env_file: .env`.
- **[DECIDED] CI/CD — push-based:** GitHub Actions builds images on push → pushes to **GHCR** → deploys over SSH to the existing **Ubuntu LTS VPS** (`docker compose pull && docker compose up -d`). Version-pinned and predictable.
- **[DECIDED] Box provisioning:** VPS already exists (Ubuntu LTS) — a one-shot Ansible playbook (or bootstrap script) installs Docker + Compose and clones the repo; secrets are injected via the `.env` file, never committed.
- **Backups & health:** use a sync-server image (`chrislongros/anki-sync-server-enhanced:latest`) and snapshot both the sync-server data (`lexibot_anki-sync-data`) and headless profile (`lexibot_anki-profile`) volumes on a nightly/pre-deploy schedule.

### 4b. The one hard constraint: Anki auth bootstrap

Recent Anki (24.11 / 25.x) removed scripted `sync_login()`, so a client can't log in fully headlessly with email+password anymore. Three ways around it for our self-hosted server:

- **A. Headless Anki Desktop + AnkiConnect (recommended).** Use the `mlcivilengineer/anki-desktop-docker:main` image (browser/VNC desktop, AnkiConnect preinstalled). Point its profile at the local sync server, and log in **once** via the built-in web desktop. The authenticated profile then lives in a persistent volume (and backups), so redeploys stay zero-touch — i.e. one ~30-second manual step at first provisioning, fully unattended thereafter. The self-hosted sync server requires `SYNC_USER1` to be configured in `.env` (e.g. `SYNC_USER1=anki:password`) for authentication.
- **B. `anki` Python lib, direct.** The bot opens a collection with the `anki` package, adds notes, and calls `col.sync_collection(SyncAuth(...))` against the local server. Avoids running a desktop, but auth + sync-conflict handling is fiddlier and less battle-tested.
- **C. genanki `.apkg`.** No login needed, but no auto-sync — already rejected.

**[DECIDED — Q1] Approach A** (headless Anki + AnkiConnect). Default plan: one ~30-second manual login at first provisioning, then fully unattended.

> **Zero-touch level — still open.** For _truly_ zero-touch from bare metal (no manual login ever), we'd script the one-time login via Xvfb automation during provisioning and snapshot the resulting profile. Doable, but more fragile. **Defaulting to the one-time login** unless you ask for the stricter version.

## 5. Input handling

Three message formats he sends:

1. **Single word** → one card.
2. **List of words** (newline/comma separated) → batch; LLM calls in **10-word chunks**; one card per word.
3. **Word + specific meaning** (e.g. `bank — riverside`) → pass the disambiguating meaning to the LLM so the card targets that exact sense.

**[DECIDED — Q5] No strict delimiter.** The bot does light pre-splitting for batching (newlines / commas → candidate items), then passes each raw item to the LLM and lets it infer intent — whether it's a bare word or a `word + intended sense`, and which token is the target word. This avoids brittle parsing and handles `bank - riverside`, `bank: riverside`, `bank (riverside)`, etc. uniformly.

## 6. Card / note structure

**[DECIDED — Q4] Note type: `Eng Vocab 2 Examples`** (confirmed from your screenshot; single `Card 1` template, **no image field** — consistent with deferring the memory image). LLM output maps to the fields as:

| Note field                         | Source                                    |
| ---------------------------------- | ----------------------------------------- |
| `Word`                             | `<pos>:<headword>` (see POS prefix below) |
| `Word Pronunciation`               | `[sound:…]` for the word audio            |
| `English Meaning`                  | `en_meaning`                              |
| `Example Sentence 1`               | `sentence_1`                              |
| `Example Sentence Pronunciation 1` | `[sound:…]` for sentence-1 audio          |
| `Example Sentence 2`               | `sentence_2`                              |
| `Example Sentence Pronunciation 2` | `[sound:…]` for sentence-2 audio          |
| `Sinhala Meaning`                  | `si_meaning`                              |

**Part-of-speech prefix (your deck convention).** Existing entries store the `Word` field as `<pos>:<word>` — e.g. `adj:artificial`, `n:adaptation`, `v:allocate`, `adv:accurately`. So the LLM also classifies part of speech (`adj` / `adv` / `n` / `v` / …) and we compose `Word = "<pos>:<headword>"`. When a sense is supplied (`word — meaning`), the POS follows that intended sense.

**[DECIDED] Media filenames.** Namespaced as `tgb_<headword>_<shorthash>.mp3` (+ `_ex1` / `_ex2`), where the hash covers text + voice — so our files never collide with his existing `nn_…` media. On an upsert we deliberately replace that word's three files. Referenced via `[sound:…]` in the three pronunciation fields.

**[UPDATED] Upsert, don't skip.** No duplicate-skipping in v1. New cards go to `Daily` with `allowDuplicate: true`. If the same word already exists, we **rewrite it in place** (`updateNoteFields` + replace its media) instead of adding a second copy. Match key = the full `Word` value (`<pos>:<headword>`), **collection-wide** — so `n:record` and `v:record` upsert independently. (Skip-dedup can be added later if wanted.)

**[DECIDED] Target deck: `Daily`.**

**[DECIDED] Tags.** Every bot-created card is tagged `tgbot` plus a date tag `added::YYYY-MM-DD` (Asia/Colombo local day) for easy filtering, review, and bulk-undo.

## 7. LLM workflow

- Single structured call per 10-word chunk returning JSON containing a list of objects with fields: `{headword, part_of_speech, is_valid_word, en_meaning, si_meaning, sentence_1, sentence_2}` via `google-genai` structured output (Pydantic schema `ChunkResponse`). The `Word` field is then composed as `"<part_of_speech>:<headword>"` to match the deck's existing convention (e.g. `adj:artificial`).
- **[DECIDED — Q6] Both models, selectable.** Expose model choice as config (and optionally a `/model` bot command): `gemini-3.5-flash` (default — cheaper/faster) and `gemini-3.1-pro-preview` (higher quality). Same `google-genai` call path; only the model string changes.
- **Free tier:** `gemini-3.5-flash` **has a free tier** (~10 RPM / ~1,500 RPD / ~250K TPM; free-tier inputs may be used to improve Google's products). `gemini-3.1-pro-preview` is **paid-only** — Google removed Pro models from the free API tier on Apr 1, 2026 ($2 / $12 per 1M in/out). So Flash is the free default; Pro incurs cost per call.
- **[DECIDED] TTS — MAI-Voice-2** (Azure AI Foundry, resource `centurion-us`, confirmed in your subscription). From the Foundry code sample: use the Azure Speech SDK with `speechsdk.SpeechConfig(subscription=speech_key, endpoint=base_endpoint)` where `base_endpoint = https://centurion-us-resource.cognitiveservices.azure.com/`; input is **plain text or SSML** (use SSML for pacing/emphasis, specifying `<voice name="en-US-Harper:MAI-Voice-2">` or `<voice name="en-US-Ethan:MAI-Voice-2">`); set `set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3)` so files are Anki-friendly. Generate audio for the word + both example sentences, store each via AnkiConnect `storeMediaFile`, and reference with `[sound:...]` in the fields.
- ✅ **Region/credits resolved:** the `centurion-us` resource is in your subscription, so the earlier US-region concern no longer applies.
- **[DECIDED] Voice — `en-US-Harper:MAI-Voice-2` (default, female) ↔ `en-US-Ethan:MAI-Voice-2` (male)** via a `VOICE_GENDER` config; both are the style-capable, most natural en-US MAI-Voice-2 voices. (Also available: `en-US-Iris` F; `en-US-Grant` / `en-US-Jasper` M.)
- **[DECIDED] SSML pacing for A2–B1:** the **word** is synthesized slightly slower (`<prosody rate="-15%">`) for clarity; example sentences at near-normal rate, neutral style; 24 kHz mp3.
- **[DECIDED] Gemini key rotation:** a pool of API keys in `.env` (comma-separated), used **round-robin with per-key RPM tracking**; on a `429` the key enters cooldown and the worker advances to the next — letting concurrency scale with the number of keys.

## 8. Robustness (you flagged this as critical)

- Durable per-word job queue with retries + idempotency (don't double-add on retry).
- Progress feedback in Telegram (queued → generating → added), polling-style.
- Graceful partial failure (e.g. card added without audio if TTS fails, flagged for retry).
- **[DECIDED — Q7] Access control:** whitelist **two** Telegram user IDs (your brother and you); silently ignore everyone else.

## 9. Assumptions & open items

### Working assumptions (proceeding on these unless you override)

These were previously implicit; now stated explicitly so nothing is ambiguous:

- **Models:** default `gemini-3.5-flash` (free tier); `gemini-3.1-pro-preview` only when explicitly selected.
- **Audio scope:** generate TTS for the **word + both example sentences** (3 clips per card), mp3.
- **Meaning language:** every card carries **both** English and Sinhala meaning.
- **Duplicates:** **upsert** — an existing word is rewritten in place (match on `<pos>:<headword>`, collection-wide, `allowDuplicate: true`); no skipping in v1.
- **Access:** whitelist exactly **two** Telegram user IDs (your brother + you); everyone else ignored.
- **Infra:** `bot` + `worker` + `redis` + headless Anki + sync server all run on the **one existing Ubuntu LTS VPS**; push-based CI/CD (GitHub Actions → GHCR → SSH); Caddy TLS.
- **Anki auth:** **one-time manual login** at first provisioning, fully unattended thereafter.
- **Sentence difficulty:** default **CEFR A2–B1** unless you specify otherwise.
- **Input parsing:** no strict delimiter — the LLM infers a bare word vs `word — sense`, and silently corrects typos to the intended headword.
- **Progress UX:** single in-place status message for batches; preview-before-commit only for single words.

### Still need from you (data)

1. ✅ **Note type — RESOLVED.** `Eng Vocab 2 Examples`; fields mapped in §6, including the new `<pos>:<word>` convention.
2. ✅ **Target deck — RESOLVED.** `Daily`.
3. ✅ **Voice — RESOLVED.** `en-US-Harper` (female default) ↔ `en-US-Ethan` (male) toggle.

### Confirmed (now locked)

- **[DECIDED] Anki auth:** one-time manual login at first provisioning, fully unattended thereafter.
- **[DECIDED] Audio scope:** word + both example sentences (3 clips per card), mp3.
- **[DECIDED] Sentence difficulty:** CEFR A2–B1.
- **[DECIDED] Voice handling:** start with a sensible MAI-Voice-2 US default; swap to a chosen playground voice later if desired.

**All inputs resolved and the full design was stress-tested (§12) — the plan is build-ready.**

## 10. Suggested tech stack

**Language:** Python 3.12 — the whole domain (Anki, Gemini, Azure Speech) has first-class Python SDKs, and Anki itself is Python.

**Telegram bot:** `aiogram` 3.x (async; supports Bot API 9.1 `sendChecklist`); webhook received via `FastAPI` + `uvicorn`, fronted by Caddy.

**Background processing:** `ARQ` (asyncio-native task queue) on `Redis` for the per-word job queue, retries, and 10-word LLM chunking; Redis also holds transient job/progress state.

**Persistence:** `SQLite` (via `SQLModel` / `aiosqlite`) for durable records — processed-word idempotency keys, per-user settings, audit log. (Move to Postgres only if it grows.)

**LLM:** `google-genai` (Google Gen AI SDK) with Pydantic structured output. Default `gemini-3.5-flash`; optional `gemini-3.1-pro-preview`.

**TTS:** `azure-cognitiveservices-speech` → MAI-Voice-2 (`centurion-us`), mp3 output.

**Anki:** AnkiConnect JSON API (called with `httpx`) inside a headless Anki desktop container; self-hosted `anki` sync server.

**Shared libs:** `httpx` (async HTTP), `pydantic` v2 + `pydantic-settings` (config/secrets), `telegramify-markdown` (clean Telegram rendering), `structlog` (logging), `tenacity` (retry/backoff).

**Infra:** Docker + Docker Compose (services: `bot`, `worker`, `redis`, `anki-headless`, `anki-sync-server`, `caddy`); Caddy for automatic TLS; GitHub Actions → GHCR → SSH deploy; Ansible/bootstrap for the VPS.

**Dev quality:** `uv` (deps), `ruff` (lint + format), `mypy` (types), `pytest` + `pytest-asyncio` + `respx` (tests), `pre-commit`.

### 10a. Codebase & Module Structure

The package is structured as a modular Python application under `src/lexibot/`:

- `src/lexibot/`
  - `__main__.py` — Package entrypoint.
  - `app.py` — FastAPI application configuration and webhook setup.
  - `config.py` — Config parsing using `pydantic-settings` (prefixed with `VB_`).
  - `container.py` — Dependency injection container.
  - `logging.py` — Structured logging configuration (scrubbing secrets from `structlog`).
  - `anki/` — AnkiConnect interface, media storage, and upsert pipeline (`connect.py`, `media.py`, `upsert.py`).
  - `bot/` — Telegram bot layers: handlers, middlewares, rendering helpers, keyboards (`dispatcher.py`, `rendering.py`, `keyboards.py`).
  - `core/` — Core types, domain models, pipeline logic, and parsers (`pipeline.py`, `parsing.py`, `exceptions.py`).
  - `db/` — Database engine configuration and repository pattern implementations (`engine.py`, `tables.py`, `repositories.py`).
  - `llm/` — Gemini API integration, key pool rotation logic, prompts, and schema (`gemini.py`, `keypool.py`, `schema.py`).
  - `observability/` — Failure alerts and health checks (`alerts.py`).
  - `tts/` — Text-to-speech integration with MAI-Voice-2 via Azure Speech SDK (`mai_voice.py`, `ssml.py`).
  - `worker/` — ARQ worker definitions and background processing task settings (`tasks.py`, `settings.py`, `enqueue.py`).

## 11. UX enhancements

Selected improvements to build on top of the robustness layer (§8):

- **[DECIDED] Preview-before-commit (single words only).** For a single word, reply with the generated card — En + Si meaning, both example sentences, and playable audio — plus inline buttons: **✅ Add / 🔄 Regenerate / ✏️ Fix sense / ❌ Discard**. This catches a wrong sense before it reaches the deck. **Skipped for batches** (lists go straight through to keep bulk adds friction-free).
- **[DECIDED] Live progress on one message.** For batches, edit a single status message in place (`editMessageText`) — e.g. “⏳ 7/20 done” → final summary — instead of posting a new message per word. Avoids notification spam and Telegram rate limits.
- **[DECIDED] Spell-tolerant input (silent).** The LLM always infers and uses the intended/corrected headword; we do **not** surface the correction or ask for confirmation. A typo like `definately` just produces a correct `definitely` card.
- **[DECIDED] Sense disambiguation.** When the LLM flags that a word has multiple common senses (e.g. _bank_), offer inline buttons to pick the intended one rather than silently guessing. (Skipped when the user already supplied a sense via the `word — meaning` format.)
- **[DECIDED] Typing / record indicator.** Fire `sendChatAction` (`typing`, then `record_voice` while generating audio) so the bot feels responsive during processing.
- **[DECIDED] Human error messages.** Friendly, actionable copy with a retry button — never raw stack traces or error codes.
- **[DECIDED] Graceful offline queueing.** If Anki/sync is down, accept the word, reply “saved — will add when Anki is back,” persist it in the durable queue, and auto-flush when the service is healthy again.

### 11a. Memory image on the card — [DEFERRED to next release]

> **Out of scope for v1.** Documented here for later; not part of the initial build.

Goal: attach a small, relevant picture to each card — a well-known retention booster for vocab. Two ways to source the image, then one shared mechanism to attach it.

**Sourcing options:**

- **Option 1 — Stock photo search (recommended start).** Query a free image API with the headword and take the top hit. **Pexels** and **Pixabay** are the easiest (free API key, generous limits, no per-image attribution required); **Unsplash** is also free but requires attribution + a “trigger download” call. Pros: free, fast, real photos — great for concrete nouns (`apple`, `bridge`). Cons: weak for abstract words (`although`, `meanwhile`).
- **Option 2 — AI-generated image.** Generate a custom illustration with an image model — Google **“Nano Banana” / Gemini 3 Pro Image**, or **Imagen 4 Fast** (~$0.02 / image). Pros: works for abstract words, consistent art style, can depict the exact sense. Cons: costs per image, slower, occasionally literal/odd. Good as a fallback when stock search returns nothing useful.

> Suggested policy: try stock search first; if no good match (or the word is abstract), fall back to AI generation. Skippable per-user via settings.

**Attaching it to the card (mechanism):** AnkiConnect's `addNote` accepts a `picture` field — a list of `{ url | data | path, filename, fields: […] }` — that **downloads and stores the image, then inserts an `<img>` tag into the named field(s)** automatically. (Equivalently: fetch the bytes yourself → `storeMediaFile` with base64 → put `<img src="word.jpg">` in an image field.) This requires his note type to have an **image field**; if it doesn't, that's a one-line addition to the note type, or we drop the image into an existing field.

## 12. Locked design decisions (stress-test session)

A relentless, branch-by-branch review resolved every remaining dependency. Summary:

**Transport & infra**

- **Telegram transport:** **webhook** (routing requests `/webhook` and `/healthz` to port 8080 of the bot).
- **Caddy proxy:** Caddyfile routes incoming requests using `handle` blocks, reading the `DOMAIN` variable from `.env`.
- **Headless Anki image:** `mlcivilengineer/anki-desktop-docker:main` (browser desktop + AnkiConnect on port 8765) for an easy one-time login.
- **No startup checks:** assume `Daily` and `Eng Vocab 2 Examples` already exist; `addNote` surfaces an error if not.
- **CI/CD:** build + push image on push to `master`; **deploy on a version tag** (`vX.Y.Z`); keep the last ~5 GHCR images for rollback.
- **Secrets:** `.env` with locked file permissions on the VPS (variables prefixed with `VB_`, plus `SYNC_USER1` for the sync server).
- **Backups:** nightly + pre-deploy snapshots of both the sync server (`lexibot_anki-sync-data`) and headless profile (`lexibot_anki-profile`) volumes; retain 7 daily + 4 weekly via a snapshot script.
- **Worker settings:** `WorkerSettings` defines `redis_settings` using a safe class attribute with a `try-except` fallback to allow imports/builds without a `.env` file.

**Generation pipeline**

- **LLM batching:** one structured call per 10-word chunk (array output); per-item fallback to single-word calls on validation failure.
- **Worker concurrency:** `min(#keys, 3)` parallel LLM chunks; **TTS capped at 4** concurrent with backoff.
- **Rate limits:** backoff + retry; the key-pool rotation absorbs Flash free-tier `429`s.
- **Invalid / non-English input:** skip just that item with a short note, continue the batch.
- **Batch size:** soft cap ~50 words/message (warn but still process).

**Anki write path**

- **Duplicates:** **upsert** (rewrite in place), match on `<pos>:<headword>` collection-wide, `allowDuplicate: true`.
- **Sync cadence:** **debounced** — one `sync` per batch + on idle, not per card.
- **Idempotency:** ARQ job id = `hash(user + pos:headword)` to coalesce rapid resends; upsert as backstop.
- **Media naming:** `tgb_<headword>_<hash>.mp3` (+ `_ex1` / `_ex2`), namespaced away from his `nn_` files.
- **Tags:** `tgbot` + `added::YYYY-MM-DD` (Asia/Colombo).

**TTS**

- **Voice:** `en-US-Harper` (female default) ↔ `en-US-Ethan` (male) via `VOICE_GENDER`.
- **SSML:** word slowed ~15%, sentences near-normal, neutral style; 24 kHz mp3.

**UX**

- **Single-word preview:** ✅ Add / 🔄 Regenerate / ✏️ Fix sense / ❌ Discard (**text-only — no in-chat audio preview**). "Fix sense" prompts for the intended meaning, then regenerates.
- **Batch summary:** one **native Telegram checklist** — ✅ added / ♻️ rewritten / ⏭️ skipped — edited in place from the live counter.
- **Whitelist bootstrap:** `/start` echoes the sender's numeric ID; you set the two allowed IDs in `ALLOWED_IDS`.
- **Migrations:** SQLModel `create_all` for v1; adopt **Alembic** at the first schema change.

**Observability**

- **Failure alerts:** Telegram DM to admin on repeated failures.
- **Logs:** structlog JSON to stdout (Docker `json-file`, rotated 10 MB × 5), shipped to **Datadog Student Pro** (free via GitHub Student Pack — 10 hosts, 500 GB logs/mo, alerts).

## 13. References

- Anki self-hosted sync server
- AnkiConnect
- genanki
- Gemini 3.5 Flash · Gemini 3.1 Pro · Google Gen AI SDK
- MAI-Voice (Azure AI Foundry)
- Telegram Bot API · AnkiConnect addNote / duplicate options / picture field
- Pexels API · Unsplash API · Gemini image generation (Nano Banana / Imagen)
- Heroku ephemeral filesystem · Headless Anki login limitation
