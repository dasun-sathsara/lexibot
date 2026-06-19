# Implementation Notes

Assumptions made and deviations from the spec docs, with rationale.

## Assumptions

**Card model (`Card` class).** The architecture never fully defines `Card`'s fields or
constructor. I inferred the shape from plan §6 (8 Anki fields), architecture §7.3
(`card.fields`, `card.media`, `card.word_field`), and the media-naming contract
(UPSERT-06/07). `Card` is frozen pydantic, carries a `tuple[MediaClip, ...]`, and exposes
`.fields` as a dict mapping to all 8 note-type field names.

**`findNotes` query escaping (UPSERT-04).** The architecture sketch omits backslash-escaping.
I escape backslashes first, then double-quotes (`escape_query_term`), which is the correct
Anki search syntax order. This is a pure function tested directly (no mock needed).

**`except*` / `return` (PIPE-02/03).** Python does not allow `return` inside an
`except*` block. I use a boolean flag (`failed`) set in the except clause and return after
the try/except. Behaviorally identical to the architecture sketch.

**Config list fields.** `pydantic-settings` attempts `json.loads` on complex (list) env
vars before validators run. `VB_GEMINI_API_KEYS=k1,k2,k3` is valid CSV but invalid JSON,
causing a `SettingsError`. Fix: annotate `gemini_api_keys` and `allowed_ids` with
`Annotated[..., NoDecode]` so the raw string reaches the `field_validator`.

**Job-id normalization at enqueue time.** The spec says job id includes `pos:headword`
(architecture §1.4), but POS is unknown at enqueue (LLM hasn't run yet). I normalize
using the raw headword only (`w:{user_id}:{casefold(headword)}`). Post-LLM, the Anki
upsert is the backstop for any race that produces a duplicate (IDEM-04).

**Structlog processor signature.** mypy --strict requires `MutableMapping[str, Any]` for
the event dict parameter, not `dict[str, Any]`.

**SUM-04 test.** `telegramify_markdown.markdownify` preserves valid markdown constructs
(`*bold*` → `_bold_`) while escaping stray specials. The test asserts that `+`, `(`, `)`,
`.` are escaped rather than testing `_` or `*` (which the library treats as markup).

## Deviations

**Docker/Compose/Caddyfile skipped** at user's explicit request. The CI workflow
(`deploy.yml`) still references `docker compose` for the VPS deploy step and the GHCR
image build, so the infra is described but the files are not present in this repo.

**Mock-dependent tests omitted** at user's explicit request: UPSERT-01/02/03/05,
RETRY-01..06, PIPE-01..06, VALID-01..05, AUTH-01/02, IDEM-03/04. All corresponding code
is fully implemented; only the test files are absent.

**SUM-\* tests added** (rendering is pure logic with no mocks needed), going slightly
beyond the "pure-logic only" scope but strictly within spec §10.

**`update_note_tags` added to `AnkiConnectClient` Protocol.** The architecture sketch
shows only `update_note_fields` in the upsert path, but the plan requires `tgbot` +
`added::date` tags on every write. Adding the tag action to the protocol is the minimal
correct fix.
