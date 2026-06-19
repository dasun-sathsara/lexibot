<aside>
🏗️

Companion to the Preliminary Plan. This document is the **technical architecture**: repository layout, module boundaries, runtime topology, and the Python conventions the build follows. Every behavioral decision references the plan's §12.

</aside>

## 1. Engineering baseline

| Area          | Choice                                       | Notes                                                                                                                 |
| ------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Language      | **Python 3.12+**                             | `match` statements, `StrEnum`, `asyncio.TaskGroup`, `ExceptionGroup`, `tomllib`, `typing.Self`, PEP 695 type aliases. |
| Packaging     | **`uv`** • `pyproject.toml` (PEP 621)        | Single source of truth for deps + tool config; `uv.lock` committed.                                                   |
| Layout        | **`src/` layout**                            | Prevents accidental imports of the un-installed package; enforces editable installs in tests.                         |
| Lint/format   | **`ruff`**                                   | Replaces flake8/isort/black; one tool.                                                                                |
| Types         | **`mypy --strict`** • `pydantic.mypy` plugin | Fully typed; Protocols for all external adapters.                                                                     |
| Runtime model | **async-first**                              | `aiogram` 3.x, `httpx.AsyncClient`, `aiosqlite`, ARQ.                                                                 |
| Tests         | **`pytest` • `pytest-asyncio` • `respx`**    | Adapters mocked at the HTTP boundary.                                                                                 |

## 2. Repository structure

A `src/` layout with one installable package (`lexibot`), split by **bounded context** rather than by technical layer — each integration (LLM, TTS, Anki) is an isolated adapter behind a Protocol.

```
lexibot/
├── pyproject.toml            # PEP 621 metadata + ruff/mypy/pytest config
├── uv.lock
├── .env.example
├── .pre-commit-config.yaml
├── Dockerfile                # multi-stage, uv-based
├── docker-compose.yml        # bot, worker, redis, anki-headless, anki-sync-server, caddy
├── Caddyfile
├── .github/workflows/
│   ├── ci.yml                # ruff + mypy + pytest on PR/push
│   └── deploy.yml            # build→GHCR on master; deploy on vX.Y.Z tag
├── deploy/
│   ├── ansible/              # one-shot VPS provisioning
│   └── backup/snapshot.sh    # nightly + pre-deploy collection snapshots
├── src/lexibot/
│   ├── __init__.py
│   ├── __main__.py           # `python -m lexibot` → launches webhook app
│   ├── config.py             # pydantic-settings Settings + get_settings()
│   ├── logging.py            # structlog + Datadog formatting
│   ├── app.py                # FastAPI app, webhook route, lifespan wiring
│   ├── container.py          # composition root (builds adapters, DI)
│   ├── bot/
│   │   ├── dispatcher.py     # aiogram Dispatcher + router registration
│   │   ├── handlers/
│   │   │   ├── commands.py   # /start, /model, /help
│   │   │   ├── words.py      # free-text word(s) ingestion
│   │   │   └── callbacks.py  # Add / Regenerate / Fix sense / Discard
│   │   ├── keyboards.py      # inline keyboards
│   │   ├── rendering.py      # telegramify-markdown, checklist summaries
│   │   └── middlewares/
│   │       ├── auth.py       # ALLOWED_IDS whitelist
│   │       └── context.py    # request-scoped structlog binding
│   ├── core/
│   │   ├── enums.py          # PartOfSpeech(StrEnum), ItemOutcome
│   │   ├── models.py         # pydantic domain models (Sense, Card, RawItem)
│   │   ├── exceptions.py     # typed error hierarchy
│   │   ├── parsing.py        # split message → candidate items
│   │   └── pipeline.py       # per-word orchestration (LLM → TTS → Anki)
│   ├── llm/
│   │   ├── ports.py          # LanguageModel Protocol
│   │   ├── gemini.py         # google-genai impl
│   │   ├── keypool.py        # round-robin + per-key cooldown
│   │   ├── prompts.py
│   │   └── schema.py         # structured-output response model
│   ├── tts/
│   │   ├── ports.py          # Synthesizer Protocol
│   │   ├── mai_voice.py      # azure-cognitiveservices-speech impl
│   │   └── ssml.py           # SSML builder (rate, voice selection)
│   ├── anki/
│   │   ├── ports.py          # AnkiGateway Protocol
│   │   ├── connect.py        # AnkiConnect over httpx
│   │   ├── upsert.py         # find → update | add (allowDuplicate)
│   │   └── media.py          # tgb_<word>_<hash> naming + storeMediaFile
│   ├── worker/
│   │   ├── settings.py       # ARQ WorkerSettings
│   │   ├── tasks.py          # process_chunk / process_word
│   │   └── enqueue.py        # job-id idempotency helpers
│   ├── db/
│   │   ├── engine.py         # async engine + session factory
│   │   ├── tables.py         # SQLModel tables
│   │   └── repositories.py   # data access (settings, audit, idempotency)
│   └── observability/
│       └── alerts.py         # admin Telegram DM on repeated failures
└── tests/
    ├── conftest.py
    ├── unit/
    └── integration/
```

**Why this shape**

- **Ports & adapters (hexagonal).** `core/pipeline.py` depends only on `*/ports.py` Protocols, never on `google-genai`, the Azure SDK, or AnkiConnect directly. Swapping the TTS provider or model is a one-file change and trivially mockable in tests.
- **`container.py` as composition root.** All concrete adapters are constructed once at startup and injected; no global singletons reaching into SDKs.
- **Bot vs worker separation.** The aiogram/FastAPI process only validates, enqueues, and renders replies. All slow work (LLM, TTS, Anki writes) runs in the ARQ worker so the webhook returns immediately.

## 3. Runtime topology

```
      Telegram
         │  HTTPS webhook
         ▼
┌──────────────────┐   enqueue (ARQ)   ┌──────────────────┐
│  bot (FastAPI +  │ ────────────────▶ │   redis (broker  │
│  aiogram)        │                   │   + job state)   │
│  auth, parse,    │ ◀──── progress ── │                  │
│  render replies  │                   └────────┬─────────┘
└──────────────────┘                            │ dequeue
         ▲                                       ▼
         │ edit message               ┌──────────────────┐
         │  (live counter)            │  worker (ARQ)    │
         └────────────────────────────│  pipeline:       │
                                      │  LLM→TTS→Anki    │
                                      └───┬─────┬─────┬──┘
                       google-genai ◀─────┘     │     └────▶ AnkiConnect
                       (key pool)               │            (anki-headless :8765)
                         MAI-Voice-2 ◀───────────┘                  │ debounced sync
                         (Azure Speech)                            ▼
                                                           anki-sync-server ──▶ phone
```

All services run on the single Ubuntu LTS VPS via Docker Compose; **Caddy** terminates TLS and proxies the webhook. `anki-headless` and `anki-sync-server` hold persistent volumes; everything else is stateless and replaceable.

## 4. Request lifecycle

1. **Ingress** — Telegram → Caddy → FastAPI webhook → aiogram dispatcher.
2. **Auth middleware** — drop anything whose sender id ∉ `ALLOWED_IDS` (silent).
3. **Parse** — `core/parsing.py` light-splits the message into candidate items (newlines/commas); no strict delimiter.
4. **Enqueue** — items are batched into 10-word chunks; each enqueued with a deterministic job id (`w:<user>:<pos?>:<raw>`), so rapid resends coalesce. The bot immediately posts a status message.
5. **Worker** — `process_chunk` runs one structured LLM call → fans out per-item `process_word`:
   - generate the three audio clips concurrently (`TaskGroup`),
   - store media, upsert the note,
   - update the shared progress counter.
6. **Sync** — after the chunk drains (and on idle), the worker calls AnkiConnect `sync` once (debounced).
7. **Reply** — the bot edits the original message into a native checklist: ✅ added / ♻️ rewritten / ⏭️ skipped.

## 5. Configuration (`config.py`)

Typed, validated, secret-aware settings via `pydantic-settings`; secrets are `SecretStr`, lists parse from comma-separated env vars.

```python
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="VB_", extra="ignore"
    )

    telegram_token: SecretStr
    allowed_ids: list[int] = Field(default_factory=list)

    gemini_api_keys: list[SecretStr]          # VB_GEMINI_API_KEYS="k1,k2,k3"
    gemini_model: str = "gemini-3.5-flash"

    azure_speech_key: SecretStr
    azure_speech_endpoint: str
    voice_gender: Literal["female", "male"] = "female"

    ankiconnect_url: str = "http://anki-headless:8765"
    target_deck: str = "Daily"
    note_type: str = "Eng Vocab 2 Examples"

    redis_dsn: str = "redis://redis:6379/0"
    database_url: str = "sqlite+aiosqlite:///data/vocab.db"

    datadog_api_key: SecretStr | None = None
    tz: str = "Asia/Colombo"

@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

## 6. Domain model (`core`)

Modern enums and immutable pydantic models keep the pipeline boundaries explicit.

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict

class PartOfSpeech(StrEnum):
    NOUN = "n"
    VERB = "v"
    ADJECTIVE = "adj"
    ADVERB = "adv"
    PREPOSITION = "prep"
    CONJUNCTION = "conj"
    PRONOUN = "pron"
    PHRASE = "phr"

class ItemOutcome(StrEnum):
    ADDED = "added"
    REWRITTEN = "rewritten"
    SKIPPED = "skipped"

class Sense(BaseModel):                     # ← Gemini structured output
    model_config = ConfigDict(frozen=True)
    headword: str
    part_of_speech: PartOfSpeech
    is_valid_word: bool
    en_meaning: str
    si_meaning: str
    sentence_1: str
    sentence_2: str

    @property
    def word_field(self) -> str:            # "adj:artificial"
        return f"{self.part_of_speech}:{self.headword}"
```

## 7. Adapters (ports & implementations)

Each integration is a `Protocol` in `*/ports.py`; the pipeline is written against the Protocol only.

```python
from typing import Protocol

class LanguageModel(Protocol):
    async def enrich(self, items: list[str], *, sense_hint: str | None = None) -> list[Sense]: ...

class Synthesizer(Protocol):
    async def synthesize(self, text: str, *, slow: bool = False) -> bytes: ...

class AnkiGateway(Protocol):
    async def upsert(self, card: "Card") -> ItemOutcome: ...
    async def sync(self) -> None: ...
```

### 7.1 Gemini key pool (`llm/keypool.py`)

Round-robin with per-key cooldown; concurrency scales with the number of keys.

```python
import asyncio
import itertools
import time

class GeminiKeyPool:
    def __init__(self, keys: list[str], cooldown_s: float = 60.0) -> None:
        if not keys:
            raise ValueError("at least one Gemini key required")
        self._keys = keys
        self._ring = itertools.cycle(keys)
        self._until: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._cooldown_s = cooldown_s

    async def acquire(self) -> str:
        async with self._lock:
            for _ in range(len(self._keys)):
                key = next(self._ring)
                if self._until.get(key, 0.0) <= time.monotonic():
                    return key
            soonest = min(self._until.values())
        await asyncio.sleep(max(0.0, soonest - time.monotonic()))
        return await self.acquire()

    def penalize(self, key: str) -> None:        # called on HTTP 429
        self._until[key] = time.monotonic() + self._cooldown_s
```

### 7.2 SSML builder (`tts/ssml.py`)

```python
VOICES = {
    "female": "en-US-Harper:MAI-Voice-2",
    "male": "en-US-Ethan:MAI-Voice-2",
}

def build_ssml(text: str, *, gender: str, slow: bool) -> str:
    rate = "-15%" if slow else "0%"
    voice = VOICES[gender]
    return (
        '<speak version="1.0" xml:lang="en-US">'
        f'<voice name="{voice}">'
        f'<prosody rate="{rate}">{text}</prosody>'
        "</voice></speak>"
    )
```

### 7.3 Anki upsert (`anki/upsert.py`)

```python
async def upsert(self, card: Card) -> ItemOutcome:
    query = f'"note:{self.note_type}" "Word:{escape(card.word_field)}"'
    note_ids = await self._connect.find_notes(query)   # collection-wide
    if note_ids:
        await self._connect.update_note_fields(note_ids[0], card.fields)
        await self._media.attach(note_ids[0], card.media)
        return ItemOutcome.REWRITTEN
    await self._connect.add_note(card, allow_duplicate=True)
    return ItemOutcome.ADDED
```

## 8. Structured concurrency in the pipeline

The three audio clips per card are generated with `asyncio.TaskGroup` (PEP 654): if any clip fails, the group cancels siblings and raises an `ExceptionGroup`, which the worker maps to a graceful partial-failure (card added, audio flagged for retry).

```python
async def build_card(sense: Sense, tts: Synthesizer, gender: str) -> Card:
    async with asyncio.TaskGroup() as tg:
        word = tg.create_task(tts.synthesize(sense.headword, slow=True))
        ex1 = tg.create_task(tts.synthesize(sense.sentence_1))
        ex2 = tg.create_task(tts.synthesize(sense.sentence_2))
    return Card.from_sense(sense, audio=(word.result(), ex1.result(), ex2.result()))
```

Global limits are enforced with `asyncio.Semaphore`: `min(len(keys), 3)` concurrent chunks for the LLM, and a separate semaphore of 4 around `tts.synthesize`.

## 9. Persistence (`db`)

SQLite via async SQLAlchemy/SQLModel. Tables: `user_settings` (per-user model/voice), `processed_item` (idempotency keys + last outcome), `audit_log`. Schema is created with `SQLModel.metadata.create_all` for v1; **Alembic** is introduced at the first migration.

```python
from datetime import datetime
from sqlmodel import SQLModel, Field

class ProcessedItem(SQLModel, table=True):
    job_id: str = Field(primary_key=True)        # w:<user>:<pos>:<headword>
    user_id: int = Field(index=True)
    word_field: str = Field(index=True)
    outcome: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

## 10. Error handling & resilience

- **Typed exception hierarchy** in `core/exceptions.py` (`LLMError`, `TTSError`, `AnkiUnavailable`, `InvalidWord`) — handlers `match` on type for user-facing copy.
- **Retries** via `tenacity` (exponential backoff) around each adapter call; `429` additionally penalizes the offending key.
- **Idempotency** via deterministic ARQ job ids + the `processed_item` table; the Anki upsert is the final backstop.
- **Offline queueing** — `AnkiUnavailable` re-queues the item with backoff and tells the user "saved — will add when Anki is back."
- **Invalid words** — `Sense.is_valid_word == False` ⇒ outcome `SKIPPED`, batch continues.

## 11. Observability

- **`structlog`** emitting JSON to stdout; request-scoped context (user id, job id) bound in middleware.
- Docker `json-file` log driver, rotated (10 MB × 5); shipped to **Datadog Student Pro** via the Datadog agent / OTLP.
- **Alerts** — `observability/alerts.py` DMs the admin Telegram id when an item exhausts retries.

## 12. Build, packaging & CI/CD

```toml
[project]
name = "lexibot"
requires-python = ">=3.12"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "SIM", "RUF"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- **Dockerfile** — multi-stage: `uv sync --frozen` into a venv, copy into a slim `python:3.12-slim` runtime; non-root user; `python -m lexibot`.
- **`ci.yml`** — `ruff check`, `ruff format --check`, `mypy`, `pytest` on every PR/push.
- **`deploy.yml`** — on push to `master` build + push images to GHCR; on a `vX.Y.Z` tag, SSH to the VPS and `docker compose pull && up -d`. Last ~5 image tags retained for rollback.

## 13. Testing strategy

- **Unit** — pure logic (parsing, key pool, SSML, `word_field`) with no I/O.
- **Adapter tests** — `respx` mocks AnkiConnect + Gemini HTTP; the Azure SDK is wrapped so the `Synthesizer` Protocol is faked.
- **Pipeline integration** — in-memory fakes for all three ports assert outcomes (added/rewritten/skipped) and idempotency under duplicate job ids.
- **No live external calls in CI.**

## 14. Security & secrets

- Secrets in `.env` (locked perms) → `SecretStr`; never logged (structlog processor scrubs `SecretStr`).
- Whitelist enforced at middleware before any handler runs.
- Caddy-managed TLS; AnkiConnect bound to the Docker network only (not published to the host).
- Webhook validated with Telegram's secret-token header.

## 15. Deferred (tracked, not built)

- **Memory image on the card** (plan §11a) — would add an `images/` adapter package behind an `ImageSource` Protocol (stock search → AI fallback) and a `picture` payload on the Anki upsert. Out of scope for v1.

Telegram → Anki Vocabulary Bot — Unit Test Spec
