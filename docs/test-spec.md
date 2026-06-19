<aside>
🧪

Companion to the Preliminary Plan and the Architecture. This is an implementation-ready **unit test specification** for an agentic coder. It targets the tricky, high-risk parts of the system — not trivial getters. Each case lists exact input and expected behavior so tests can be written before the implementation (TDD).

</aside>

## How to use this doc

- **Scope:** pure-logic and adapter-boundary unit tests. No live network, no real Anki, no real Azure/Gemini. All I/O is faked at the Protocol or HTTP (`respx`) boundary.
- **Runner:** `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`), `respx` for httpx, `freezegun` or monkeypatched `time.monotonic` for timing.
- **Convention:** test ids below (e.g. `PARSE-04`) should map to test function names like `test_parse_04_word_plus_meaning_colon`.
- **Contracts first:** §1 fixes the behavioral contracts the tests assume. If the coder changes a contract, update these cases in lockstep.

## 1. Behavioral contracts under test

These are the precise rules the tricky tests pin down. They resolve ambiguities left implicit in the plan.

### 1.1 Message parsing contract

- The message is split into **items** by **newlines and commas** (both are item separators).
- **Spaces within an item are preserved** — multi-word phrases are valid items (`break the ice` is one item).
- An item is a **word+meaning** item if it contains a **sense delimiter**: `-` (space-hyphen-space), `—` (space-em-dash-space), or a leading-token `:` form `headword: meaning`. Split on the **first** delimiter only; the left side is the headword, the right side is the `sense_hint`.
- Hyphenated words without surrounding spaces (`well-being`) are **not** split.
- Empty/whitespace-only items are dropped.
- Leading/trailing whitespace on each side is trimmed.
- Case is preserved as typed (normalization happens later in the LLM step).

### 1.2 Word field contract

- `Word` field value = `f"{part_of_speech}:{headword}"`, POS from the `PartOfSpeech` StrEnum lowercase short code (`n`, `v`, `adj`, `adv`, `prep`, `conj`, `pron`, `phr`).
- The headword in the `Word` field is the **LLM-normalized lemma**, not necessarily the raw input.

### 1.3 Upsert contract

- Match is **collection-wide** by exact `Word` field (`<pos>:<headword>`), via `findNotes`.
- If ≥1 match → `updateNoteFields` on the first match + replace that word's media → outcome `REWRITTEN`.
- If 0 matches → `addNote` with `allowDuplicate: true` → outcome `ADDED`.
- The `findNotes` query must **escape embedded double-quotes** in the word field.

### 1.4 Idempotency contract

- ARQ job id = `f"w:{user_id}:{normalized_word_field}"` (deterministic). Re-enqueue with the same id while pending/running is a no-op (coalesced).
- The Anki upsert is the **backstop**: even if a duplicate job runs, upsert prevents a second card.

## 2. Message parsing — `core/parsing.py`

Highest-value target: ambiguity between "list of words" and "phrase" and "word+meaning."

| ID       | Input (raw message)                  | Expected items (headword │ sense_hint)                              |
| -------- | ------------------------------------ | ------------------------------------------------------------------- |
| PARSE-01 | `run`                                | [(`run`, None)]                                                     |
| PARSE-02 | `run, jump, swim`                    | [(`run`,None),(`jump`,None),(`swim`,None)]                          |
| PARSE-03 | three lines: `run` / `jump` / `swim` | 3 items, no hints                                                   |
| PARSE-04 | `bank: the financial institution`    | [(`bank`, `the financial institution`)]                             |
| PARSE-05 | `bank - the side of a river`         | [(`bank`, `the side of a river`)]                                   |
| PARSE-06 | `break the ice`                      | [(`break the ice`, None)] (one phrase, not 3 words)                 |
| PARSE-07 | `make up, run into`                  | [(`make up`,None),(`run into`,None)] (phrases preserved)            |
| PARSE-08 | `well-being`                         | [(`well-being`, None)] (hyphen not a delimiter)                     |
| PARSE-09 | `spring - the season - not the coil` | [(`spring`, `the season - not the coil`)] (split on first `•` only) |
| PARSE-10 | `run  ,  ,  jump`                    | [(`run`,None),(`jump`,None)] (trim + drop empties)                  |
| PARSE-11 | `bank:` (delimiter, empty hint)      | [(`bank`, None)] (empty hint normalized to None)                    |
| PARSE-12 | (empty / whitespace only)            | [] (no items)                                                       |
| PARSE-13 | mixed: `run, bank: money` / `swim`   | [(`run`,None),(`bank`,`money`),(`swim`,None)]                       |
| PARSE-14 | emoji/markdown noise: `**run**`      | [(`run`, None)] (strip surrounding markdown/punctuation)            |

Skeleton:

```python
import pytest
from lexibot.core.parsing import parse_message

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("run", [("run", None)]),
        ("run, jump, swim", [("run", None), ("jump", None), ("swim", None)]),
        ("bank: the financial institution", [("bank", "the financial institution")]),
        ("break the ice", [("break the ice", None)]),
        ("make up, run into", [("make up", None), ("run into", None)]),
        ("well-being", [("well-being", None)]),
        ("spring - the season - not the coil", [("spring", "the season - not the coil")]),
        ("  run  ,  ,  jump  ", [("run", None), ("jump", None)]),
        ("", []),
    ],
)
def test_parse_message(raw, expected):
    assert [(i.headword, i.sense_hint) for i in parse_message(raw)] == expected
```

## 3. Chunking & batch caps — `worker/enqueue.py`

| ID       | Scenario                          | Expected                                                                               |
| -------- | --------------------------------- | -------------------------------------------------------------------------------------- |
| CHUNK-01 | 25 items, chunk size 10           | 3 chunks: 10, 10, 5 (order preserved)                                                  |
| CHUNK-02 | exactly 10 items                  | 1 chunk of 10 (no empty trailing chunk)                                                |
| CHUNK-03 | 0 items                           | 0 chunks, no enqueue calls                                                             |
| CHUNK-04 | 65 items, soft cap 50             | first 50 processed; user warned remaining 15 were dropped (or deferred per cap policy) |
| CHUNK-05 | duplicate word twice in one batch | same job id → enqueued once (coalesced)                                                |

## 4. Gemini key pool — `llm/keypool.py`

Timing-sensitive; monkeypatch `time.monotonic` and `asyncio.sleep`.

| ID     | Scenario                                 | Expected                                                            |
| ------ | ---------------------------------------- | ------------------------------------------------------------------- |
| KEY-01 | 3 keys, 5 sequential acquires            | round-robin order k1,k2,k3,k1,k2                                    |
| KEY-02 | penalize k2, then acquire ×3             | k2 skipped while cooling: k1,k3,k1                                  |
| KEY-03 | penalize all keys                        | acquire awaits until soonest cooldown expires, then returns it      |
| KEY-04 | cooldown expiry boundary                 | key reusable exactly at `monotonic == until` (uses `<=`)            |
| KEY-05 | single key, penalized                    | acquire waits cooldown then returns the only key (no infinite loop) |
| KEY-06 | empty key list at construction           | raises ValueError                                                   |
| KEY-07 | concurrent acquires (asyncio.gather ×10) | no key handed out beyond its per-key RPM; lock prevents races       |

Skeleton:

```python
import asyncio
import pytest
from lexibot.llm.keypool import GeminiKeyPool

@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr("lexibot.llm.keypool.time.monotonic", lambda: t["now"])
    return t

@pytest.mark.asyncio
async def test_key_02_penalized_key_skipped(clock):
    pool = GeminiKeyPool(["k1", "k2", "k3"], cooldown_s=60)
    pool.penalize("k2")
    got = [await pool.acquire() for _ in range(3)]
    assert got == ["k1", "k3", "k1"]

@pytest.mark.asyncio
async def test_key_06_empty_raises():
    with pytest.raises(ValueError):
        GeminiKeyPool([])
```

## 5. SSML builder — `tts/ssml.py`

| ID      | Scenario                              | Expected                                                                                          |
| ------- | ------------------------------------- | ------------------------------------------------------------------------------------------------- |
| SSML-01 | slow=True                             | contains `rate="-15%"`                                                                            |
| SSML-02 | slow=False                            | contains `rate="0%"`                                                                              |
| SSML-03 | gender=female                         | voice name `en-US-Harper:MAI-Voice-2`                                                             |
| SSML-04 | gender=male                           | voice name `en-US-Ethan:MAI-Voice-2`                                                              |
| SSML-05 | text contains `&`, `<`, `>`, `"`, `'` | characters are XML-escaped in output (REGRESSION: current sketch does NOT escape — must be fixed) |
| SSML-06 | output is well-formed XML             | `xml.etree.ElementTree.fromstring` parses without error                                           |
| SSML-07 | unknown gender string                 | raises KeyError/ValueError (no silent default)                                                    |

<aside>
⚠️

SSML-05/06 are the important ones: a word like `rock & roll` or a sentence with a quote will produce invalid SSML and a 400 from Azure unless escaped. The architecture sketch omits escaping on purpose so the test drives the fix.

</aside>

```python
import xml.etree.ElementTree as ET
import pytest
from lexibot.tts.ssml import build_ssml

def test_ssml_05_escapes_special_chars():
    out = build_ssml('rock & "roll" <x>', gender="female", slow=False)
    assert "&amp;" in out and "&lt;" in out and "&quot;" in out
    ET.fromstring(out)  # must be well-formed

def test_ssml_07_unknown_gender():
    with pytest.raises((KeyError, ValueError)):
        build_ssml("x", gender="robot", slow=False)
```

## 6. Anki upsert & query building — `anki/upsert.py`, `anki/connect.py`

Fake the `AnkiConnect` client (Protocol) and assert decision + escaping.

| ID        | Scenario                                       | Expected                                                                               |
| --------- | ---------------------------------------------- | -------------------------------------------------------------------------------------- |
| UPSERT-01 | findNotes returns []                           | calls addNote with allowDuplicate=true; outcome ADDED                                  |
| UPSERT-02 | findNotes returns [123]                        | calls updateNoteFields(123, ...); no addNote; outcome REWRITTEN                        |
| UPSERT-03 | findNotes returns [123, 456] (dupes exist)     | updates only first (123); outcome REWRITTEN                                            |
| UPSERT-04 | word field contains a double quote             | findNotes query escapes the quote; no query-injection                                  |
| UPSERT-05 | rewrite path                                   | old media for that word replaced (storeMediaFile called with same 3 filenames)         |
| UPSERT-06 | add path media naming                          | filenames `tgb_<headword>_<hash>.mp3`, `_ex1`, `_ex2`; hash stable for same text+voice |
| UPSERT-07 | media hash differs when voice gender changes   | different filename (cache busts on voice change)                                       |
| UPSERT-08 | query targets whole collection, not just Daily | findNotes query has no `deck:Daily` constraint on the match                            |

```python
import pytest
from lexibot.core.enums import ItemOutcome

@pytest.mark.asyncio
async def test_upsert_02_existing_note_rewritten(fake_connect, sample_card):
    fake_connect.find_notes.return_value = [123]
    outcome = await make_gateway(fake_connect).upsert(sample_card)
    assert outcome is ItemOutcome.REWRITTEN
    fake_connect.update_note_fields.assert_awaited_once()
    fake_connect.add_note.assert_not_awaited()

@pytest.mark.asyncio
async def test_upsert_04_escapes_quote_in_query(fake_connect):
    card = make_card(word_field='n:say "hi"')
    fake_connect.find_notes.return_value = []
    await make_gateway(fake_connect).upsert(card)
    query = fake_connect.find_notes.call_args.args[0]
    assert r'\"' in query  # quote escaped inside the search term
```

## 7. Structured concurrency & partial failure — `core/pipeline.py`

| ID      | Scenario                           | Expected                                                                                                     |
| ------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| PIPE-01 | all 3 TTS clips succeed            | Card has 3 media; outcome ADDED/REWRITTEN                                                                    |
| PIPE-02 | one clip raises TTSError           | TaskGroup raises ExceptionGroup; pipeline catches, flags audio-retry, card still created with available text |
| PIPE-03 | all 3 clips raise                  | ExceptionGroup of 3; mapped to a single user-facing failure for that item                                    |
| PIPE-04 | TTS semaphore = 4                  | never more than 4 concurrent synthesize calls (assert max observed concurrency)                              |
| PIPE-05 | LLM chunk semaphore = min(#keys,3) | concurrency capped accordingly                                                                               |
| PIPE-06 | sibling cancellation               | when one clip fails fast, siblings are cancelled (no orphaned tasks)                                         |

```python
@pytest.mark.asyncio
async def test_pipe_04_tts_concurrency_capped():
    gate = ConcurrencyProbe(limit_expected=4)
    tts = ProbingSynthesizer(gate)
    await run_pipeline(items=make_items(20), tts=tts)
    assert gate.max_observed <= 4
```

## 8. Retry / backoff / 429 handling — adapters + `tenacity`

| ID       | Scenario                                   | Expected                                                                                            |
| -------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| RETRY-01 | Gemini returns 429 once then 200           | offending key penalized; call retried; succeeds; result returned                                    |
| RETRY-02 | Gemini 429 on every key                    | retries exhausted → LLMError; item marked failed, batch continues                                   |
| RETRY-03 | transient 503 from AnkiConnect             | retried with backoff; eventually succeeds                                                           |
| RETRY-04 | AnkiConnect connection refused (Anki down) | raises AnkiUnavailable → item re-queued with backoff, user told "saved, will add when Anki is back" |
| RETRY-05 | backoff is bounded                         | retry count and max delay capped (no infinite retry); assert attempts == configured max             |
| RETRY-06 | non-retryable 400 from Azure               | not retried; surfaces TTSError immediately                                                          |

Use `respx` to script status-code sequences; assert `pool.penalize` called with the right key on 429.

## 9. Idempotency — `worker/enqueue.py`, `worker/tasks.py`

| ID      | Scenario                                     | Expected                                                                |
| ------- | -------------------------------------------- | ----------------------------------------------------------------------- |
| IDEM-01 | job id determinism                           | same (user, pos, headword) → identical job id string                    |
| IDEM-02 | different user, same word                    | different job id (user-scoped)                                          |
| IDEM-03 | same word enqueued twice while first pending | second enqueue coalesced (one job runs)                                 |
| IDEM-04 | duplicate job actually runs (race)           | upsert backstop → still one card (REWRITTEN second time, not a 2nd ADD) |
| IDEM-05 | headword normalization in job id             | `Run` and `run` map to the same id (case-folded, trimmed)               |

## 10. Outcome classification & batch summary — `bot/rendering.py`

| ID     | Scenario                            | Expected                                                     |
| ------ | ----------------------------------- | ------------------------------------------------------------ |
| SUM-01 | mix of added/rewritten/skipped      | counts correct; checklist lists each item under right bucket |
| SUM-02 | all skipped (invalid words)         | summary says 0 added, lists skipped with reason              |
| SUM-03 | summary fits Telegram length limits | long batches truncated/paged, never exceed 4096 chars        |
| SUM-04 | markdown-special chars in a word    | escaped via telegramify-markdown (no broken formatting)      |

## 11. Invalid-word handling & LLM schema — `llm/schema.py`, `core/pipeline.py`

| ID       | Scenario                                 | Expected                                                                     |
| -------- | ---------------------------------------- | ---------------------------------------------------------------------------- |
| VALID-01 | `is_valid_word == False`                 | outcome SKIPPED; no TTS, no Anki write; batch continues                      |
| VALID-02 | LLM returns malformed JSON               | schema validation error → per-item fallback retry, then SKIPPED if still bad |
| VALID-03 | chunk call returns fewer items than sent | missing items fall back to per-item calls (no silent drop)                   |
| VALID-04 | sense_hint provided                      | prompt includes the hint; targeted sense honored in output mapping           |
| VALID-05 | POS outside enum                         | validation error → item flagged, not crash                                   |

## 12. Auth, config & secret hygiene

| ID      | Scenario                             | Expected                                                |
| ------- | ------------------------------------ | ------------------------------------------------------- |
| AUTH-01 | sender id in ALLOWED_IDS             | handler runs                                            |
| AUTH-02 | sender id not in ALLOWED_IDS         | update dropped silently; no handler, no reply           |
| CONF-01 | `VB_GEMINI_API_KEYS="k1,k2,k3"`      | parsed to 3-element list                                |
| CONF-02 | `VB_ALLOWED_IDS="111,222"`           | parsed to [111, 222] (ints)                             |
| CONF-03 | missing required secret              | Settings raises validation error at startup (fail fast) |
| SEC-01  | log an object containing a SecretStr | rendered as `**********`, never the raw value           |
| SEC-02  | exception repr includes settings     | secret values not leaked in tracebacks                  |

## 13. Shared fixtures (suggested `conftest.py`)

- `fake_connect` — `AsyncMock` implementing the AnkiConnect Protocol (`find_notes`, `add_note`, `update_note_fields`, `store_media_file`, `sync`).
- `fake_tts` / `ProbingSynthesizer` — records concurrency; can be told to fail the Nth call.
- `fake_llm` — returns canned `Sense` objects; can emit malformed payloads.
- `clock` — monkeypatched `time.monotonic`; `sleep_spy` — records `asyncio.sleep` durations without waiting.
- `sample_card` / `make_card(word_field=...)` — card factory.
- `make_items(n)` — generates n parsed items.
- `respx_mock` — for Gemini/Azure/AnkiConnect HTTP-level tests.

## 14. Priority order for the coder

1. `PARSE-*` (correctness of everything downstream depends on it)
2. `UPSERT-*` (data-integrity / no duplicate cards)
3. `KEY-*` + `RETRY-*` (resilience under rate limits)
4. `SSML-05/06` (silent Azure 400s)
5. `PIPE-*` (partial-failure robustness)
6. `IDEM-*`, then the rest.
