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
| `VB_WEBHOOK_SECRET` | | — | Secret header token for webhook validation |
| `VB_VOICE_GENDER` | | `female` | `female` (Harper) or `male` (Ethan) |
| `VB_GEMINI_MODEL` | | `gemini-3.5-flash` | LLM model name |
| `VB_REDIS_DSN` | | `redis://redis:6379/0` | ARQ broker |
| `VB_ADMIN_ID` | | — | Telegram user ID to receive failure alerts |
| `VB_TZ` | | `Asia/Colombo` | Timezone for `added::` date tags |
| `VB_LOG_LEVEL` | | `INFO` | Log level |

## Running the test suite

```bash
uv run pytest                                          # all tests
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy src                                        # type check
```

## Docker / self-hosted deploy

All services run on a single VPS via Docker Compose:

| Service | Description |
|---|---|
| `bot` | FastAPI + aiogram webhook receiver |
| `worker` | ARQ worker — LLM → TTS → Anki pipeline |
| `redis` | ARQ job broker |
| `anki-headless` | Headless Anki desktop with AnkiConnect |
| `anki-sync-server` | Self-hosted Anki sync server |
| `caddy` | Reverse proxy with automatic TLS |

```bash
# Copy and fill in secrets, then set the domain
cp .env.example .env
echo "DOMAIN=bot.example.com" >> .env

# Start everything
docker compose up -d
```

Caddy handles TLS automatically via Let's Encrypt. The `DOMAIN` env var must match a
DNS A record pointing to the VPS.

### First-time Anki setup

After `docker compose up -d`, open the `anki-headless` browser desktop (it exposes a
web-based VNC on the Docker network — expose port 6080 temporarily if needed), log the
Anki profile into the local sync server, then close the desktop. The authenticated profile
is persisted in the `anki-profile` volume and survives restarts; the bot runs unattended
thereafter.

Confirm the `Daily` deck and `Eng Vocab 2 Examples` note type exist before sending the
first word.

### VPS provisioning

A one-shot Ansible playbook installs Docker + Compose and clones the repo:

```bash
ansible-playbook -i your-vps, deploy/ansible/playbook.yml
```

Nightly volume snapshots (Anki collection + sync data, 7 daily + 4 weekly):

```bash
# Add to crontab on the VPS
0 3 * * * /opt/vocab-bot/deploy/backup/snapshot.sh
```

## CI/CD

- **Every push/PR**: `ruff check`, `ruff format --check`, `mypy`, `pytest` via GitHub Actions.
- **Push to `main`**: builds and pushes a Docker image to GHCR.
- **Version tag `vX.Y.Z`**: deploys to the VPS (`docker compose pull && up -d`).

Required GitHub Actions secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`.

```bash
git tag v1.0.0 && git push origin v1.0.0
```
