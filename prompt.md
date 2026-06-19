# Task: Build the Telegram → Anki Vocabulary Bot

Build a production-quality Python service from the three specification documents in `./docs`:

- `docs/plan.md` — product requirements and all locked design decisions (the source of truth for _what_ and _why_).
- `docs/architecture.md` — the technical architecture: directory layout, module boundaries, runtime topology, and code conventions (the source of truth for _how_).
- `docs/test-spec.md` — the unit test specification with behavioral contracts, enumerated cases (PARSE-_, KEY-_, SSML-_, UPSERT-_, etc.), and skeletons.

## Ground rules

1. **Read all three docs fully before writing any code.** If the plan and architecture ever conflict, the plan wins on behavior, the architecture wins on structure.
2. **Follow the architecture exactly**: `src/` layout, package `vocab_bot`, the module boundaries and file names in §2, ports-and-adapters (Protocols in `*/ports.py`, concrete impls injected via `container.py`). Do not invent a different structure.
3. **Python 3.12+** with the modern features the architecture calls for (`StrEnum`, `asyncio.TaskGroup`/`ExceptionGroup`, `match`, frozen pydantic models, `SecretStr`). Async-first throughout.
4. **Tooling**: manage deps with `uv`; code must pass `ruff check`, `ruff format --check`, and `mypy --strict` with zero errors. Configure all tooling in `pyproject.toml` (PEP 621).
5. **No secrets, no live calls in code or tests.** All external I/O (Gemini, MAI-Voice-2, AnkiConnect) sits behind a Protocol and is faked/mocked in tests.

## Collaboration & checkpoints

- **You can pause and ask me questions at any time.** Prefer asking over guessing whenever something is ambiguous, underspecified, or a judgment call — _always_ pause for data-integrity, security, cost, or irreversible decisions. Batch related questions together so I can answer in one pass.
- **Commit after each major piece of work** (e.g. a completed module + its passing tests, or the Docker/CI setup), not in one giant commit. Use small, logical, well-described commits with conventional-commit-style messages.
- **Checkpoint between modules**: after finishing a module from the priority list, give me a 2–3 line status update (what's done, what's next, anything you assumed) and continue unless you have a blocking question.
- It's fine to proceed autonomously on unambiguous work — don't ask permission for things the docs already decide. Ask when it actually matters.

## Test-driven workflow (required)

Work module by module in the priority order from `docs/test-spec.md §14`:
`PARSE-* → UPSERT-* → KEY-* + RETRY-* → SSML-05/06 → PIPE-* → IDEM-* → rest`.

1. Implement the test cases from the test spec FIRST (use the IDs as test names, e.g. `PARSE-04` → `test_parse_04_word_plus_meaning_colon`). Honor the behavioral contracts in §1 precisely.
2. Then implement the code until those tests pass.
3. Note: a few cases are intentional regression-drivers that must FAIL against the architecture's naïve sketches and force a fix — specifically **SSML-05/06** (XML escaping) and **UPSERT-04** (escaping quotes in the `findNotes` query). Implement the hardened version so they pass; do not weaken the test to match a broken sketch.
4. Build the shared fixtures from §13 in `tests/conftest.py`.

## Deliverables

- A complete, runnable repo matching `docs/architecture.md §2`, including:
  - All `src/vocab_bot/**` modules, fully typed.
  - `tests/` covering every case in `docs/test-spec.md` (unit + the adapter/pipeline integration tests described), all green.
  - `pyproject.toml`, `uv.lock`, `.env.example` (every `VB_*` var from the config model), `.pre-commit-config.yaml`.
  - `Dockerfile` (multi-stage, uv-based, non-root), `docker-compose.yml` (bot, worker, redis, anki-headless, anki-sync-server, caddy), `Caddyfile`.
  - `.github/workflows/ci.yml` (ruff + mypy + pytest) and `deploy.yml` (build→GHCR on main, deploy on `vX.Y.Z` tag) per architecture §12.
  - `README.md`: setup, local run, env vars, deploy, and how to run the test suite.
- A short `IMPLEMENTATION_NOTES.md` recording any assumptions you made and any deviations from the docs (with rationale).

## Definition of done

- `uv run ruff check . && uv run mypy src && uv run pytest` all pass with zero errors.
- Every test ID in `docs/test-spec.md` is implemented and green.
- `docker compose config` validates and images build.
- No real API keys, tokens, or live network calls anywhere in the code or tests.

Begin by reading the three docs and outlining your build order, then check in with me before starting module 1. Proceed module by module, committing and checkpointing as you go.
