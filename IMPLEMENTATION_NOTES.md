# Implementation Notes

Assumptions made and deviations from the spec docs, with rationale.

## Assumptions

**Card model.** The architecture never fully defines `Card`'s fields or constructor. The
shape was inferred from the plan (8 Anki fields) and the media-naming contract. `Card` is
a frozen pydantic model carrying a `tuple[MediaClip, ...]` and exposing `.fields` as a
dict mapping to all 8 note-type field names.

**`findNotes` query escaping.** The architecture sketch omits backslash-escaping. The
implementation escapes backslashes first, then double-quotes (`escape_query_term`), which
is the correct Anki search syntax order. This is a pure function tested directly without
mocks.

**`except*` / `return`.** Python does not allow `return` inside an `except*` block. The
implementation sets a boolean flag (`failed`) in the except clause and returns after the
try/except. Behaviorally identical to the architecture sketch.

**Config list fields.** `pydantic-settings` attempts `json.loads` on complex (list) env
vars before validators run. `VB_GEMINI_API_KEYS=k1,k2,k3` is valid CSV but invalid JSON,
causing a `SettingsError`. Fix: annotate `gemini_api_keys` and `allowed_ids` with
`Annotated[..., NoDecode]` so the raw string reaches the `field_validator`.

**Job-id normalization at enqueue time.** POS is unknown at enqueue (the LLM hasn't run
yet). The job id uses the raw headword only (`w:{user_id}:{casefold(headword)}`). The
Anki upsert is the backstop for any race that produces a duplicate.

**Structlog processor signature.** `mypy --strict` requires `MutableMapping[str, Any]`
for the event dict parameter, not `dict[str, Any]`.

**Rendering tests.** `telegramify_markdown.markdownify` preserves valid markdown constructs
(`*bold*` → `_bold_`) while escaping stray specials. Tests assert that `+`, `(`, `)`,
`.` are escaped rather than `_` or `*` (which the library treats as intentional markup).

## Deviations

**Mock-dependent tests omitted** at user's request. All corresponding code is fully
implemented; only the test files for adapter/pipeline integration cases are absent.

**Rendering tests added** beyond the originally scoped pure-logic tests, because the
summary rendering is fully deterministic and requires no mocks.

**`update_note_tags` added to `AnkiConnectClient` Protocol.** The architecture sketch
shows only `update_note_fields` in the upsert path, but the plan requires `tgbot` +
`added::date` tags on every write. Adding the tag RPC to the protocol is the minimal
correct fix.
