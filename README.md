# vocab-bot

Telegram → Anki vocabulary bot. Send English words; receive Anki cards with Sinhala +
English meanings, two example sentences, and MAI-Voice-2 TTS audio — upserted into a
`Daily` deck via AnkiConnect and synced to a self-hosted Anki sync server.

## Quick-start (local dev)

```bash
# 1. Install uv (if needed)
brew install uv          # macOS — or see https://docs.astral.sh/uv/

# 2. Clone + install
git clone <repo>
cd vocab-bot
uv sync

# 3. Configure
cp .env.example .env     # fill in all VB_* values

# 4. Run the bot (webhook mode requires a public URL; use polling for local testing)
uv run python -m vocab_bot

# 5. Run the ARQ worker in a separate terminal
uv run arq vocab_bot.worker.settings.WorkerSettings
```

## Environment variables

All variables are prefixed `VB_`. See `.env.example` for the full list with descriptions.

| Variable | Required | Default | Description |
|---|---|---|---|
| `VB_TELEGRAM_TOKEN` | ✓ | — | Bot token from @BotFather |
| `VB_ALLOWED_IDS` | ✓ | — | Comma-separated Telegram user IDs |
| `VB_GEMINI_API_KEYS` | ✓ | — | Comma-separated Gemini API keys |
| `VB_AZURE_SPEECH_KEY` | ✓ | — | Azure Speech resource key |
| `VB_AZURE_SPEECH_ENDPOINT` | ✓ | — | Azure Speech endpoint URL |
| `VB_ANKICONNECT_URL` | | `http://anki-headless:8765` | AnkiConnect base URL |
| `VB_WEBHOOK_BASE_URL` | | — | Public HTTPS base URL for webhook |
| `VB_VOICE_GENDER` | | `female` | `female` (Harper) or `male` (Ethan) |
| `VB_GEMINI_MODEL` | | `gemini-3.5-flash` | LLM model name |
| `VB_REDIS_DSN` | | `redis://redis:6379/0` | ARQ broker |
| `VB_TZ` | | `Asia/Colombo` | Timezone for `added::` date tags |

## Running the test suite

```bash
uv run pytest                          # all tests
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy src                        # type check
```

## Deploy

Push a `vX.Y.Z` tag to trigger the GitHub Actions deploy workflow:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

The workflow builds a Docker image, pushes it to GHCR, then SSHes to the VPS and runs
`docker compose pull && docker compose up -d`. Secrets (`VPS_HOST`, `VPS_USER`,
`VPS_SSH_KEY`) must be set in the repository's GitHub Actions settings.

## Anki setup (one-time)

1. Start the `anki-headless` container and open its browser desktop (VNC/web).
2. Log the Anki profile into your self-hosted sync server.
3. Confirm the `Daily` deck and `Eng Vocab 2 Examples` note type exist.

After that first login the profile is persisted on a Docker volume and the bot runs
unattended.
