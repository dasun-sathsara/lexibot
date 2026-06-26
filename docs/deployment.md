# Comprehensive Deployment Guide

This guide outlines the step-by-step process for deploying the **lexibot** application stack onto a self-hosted Linux VPS.

---

## 1. Prerequisites
* **VPS Host**: A virtual private server running Ubuntu 24.04 (or similar modern Debian-based Linux).
  * **Memory Requirement**: A **1 GiB** instance is sufficient. The Anki container runs in `QT_QPA_PLATFORM=offscreen` mode (a vendored copy of `ThisIsntTheWay/headless-anki`), so the heavyweight QtWebEngine/VNC desktop stack that previously required ~2 GiB is gone — only Anki + AnkiConnect run on a virtual surface. A small swap file is still good hygiene for transient spikes.
  * **Swap Configuration** (optional but recommended):
    ```bash
    sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile && sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    ```
* **DNS Configuration**: A domain name (e.g. `bot.appledorelabs.dev`) with an **A record** pointing to the public IP of your VPS.
* **Port Availability**:
  * **Port 80 (HTTP)** and **Port 443 (HTTPS)** must be open to the public internet for the Caddy web server (handles the Telegram webhook + healthz only).
  * **Port 22 (SSH)** for admin access.
  * AnkiConnect (8765) is bound to the Docker internal network only and is **never published** to the host. Port 5900 (VNC) is only relevant for debugging (see §4).
---

## 2. Automated Local Deployment
Instead of manual setup or GitHub CI pipelines (which have been removed), you can build and deploy the stack directly from your local machine to the VPS using the `deploy.sh` script in the root directory:

```bash
./deploy.sh azureuser@<your-vps-ip>
```

If `DOMAIN` is configured in your local `.env`, the script will automatically resolve the target IP and run:
```bash
./deploy.sh
```

This deployment script automates:
1. Preparing the remote `/opt/lexibot` directory.
2. Syncing the local workspace (code, configurations, and pre-configured profiles) via `rsync`.
3. Running `deploy/bootstrap.sh` on the VPS to set up a 2 GiB swap space and provision Docker/Docker Compose via Ansible.
4. Building the Docker images and launching the compose stack.
5. Waiting for container health checks to pass.
---

## 3. Environment & Secrets Configuration
Create and fill the `/opt/lexibot/.env` file on the VPS:

1. Copy the example template:
   ```bash
   cp /opt/lexibot/.env.example /opt/lexibot/.env
   ```
2. Open `/opt/lexibot/.env` and configure the following variables:
   * `DOMAIN`: Your pointed domain (e.g., `bot.appledorelabs.dev`).
   * `VB_WEBHOOK_BASE_URL`: Set to `https://<your-domain>` (e.g., `https://bot.appledorelabs.dev`).
   * `VB_TELEGRAM_TOKEN`: Real Telegram Bot Token from `@BotFather`.
   * `VB_ALLOWED_IDS`: Your numeric Telegram user ID (comma-separated if multiple).
   * `VB_ADMIN_ID`: Your numeric Telegram user ID for alert notifications.
   * `VB_GEMINI_API_KEYS`: Your Gemini API Key (from Google AI Studio, comma-separated if multiple).
   * `VB_AZURE_SPEECH_KEY`: Your Azure Speech / AI Services key.
   * `VB_AZURE_SPEECH_ENDPOINT`: The Azure region code (e.g. `eastus2`). *Note: For multi-service Cognitive Services keys, this must be the region name (e.g. `eastus2`) instead of the endpoint URL to prevent 401 WebSocket errors.*
   * `VB_DATABASE_URL`: Set to `sqlite+aiosqlite:////app/data/vocab.db` (enables database persistence in the mounted `bot-data` volume). Note the four slashes (`:////`) required for an absolute path.
   * `VB_WEBHOOK_SECRET`: A secure random hex string for securing the webhook endpoint (e.g. generated via `openssl rand -hex 16`).

   There are **no sync credentials in `.env`**: the headless Anki profile syncs to AnkiWeb using credentials stored inside the copied profile, not via environment variables.

---

## 4. Headless Anki Profile Setup (COPY-PROFILE approach)

The Anki container is built from a vendored copy of `ThisIsntTheWay/headless-anki` under `deploy/anki-headless/` and runs in `QT_QPA_PLATFORM=offscreen` mode. There is **no in-container web GUI login**. Instead, you prepare a profile on a normal desktop Anki install once and copy it into the `anki-headless` `/data` volume.

The image is built via the existing GHCR pipeline (`deploy.yml`) with version-pinned build args (`ANKI_VERSION`, `ANKICONNECT_VERSION`, `QT_VERSION=6`).

1. **Prepare the profile on a desktop Anki install** (one-time, on any machine with Anki):
   * Open Anki and **sync the profile to AnkiWeb** at least once (log in with your AnkiWeb account). This stores the auth credentials inside the profile.
   * Install the **AnkiConnect** add-on: *Tools → Add-ons → Get Add-ons...* and paste code **`2055492159`**.
   * Configure AnkiConnect to listen on all interfaces. Open the AnkiConnect add-on config (*Tools → Add-ons → AnkiConnect → Config*) and set:
     ```json
     {
         "webBindAddress": "0.0.0.0",
         "webCorsOriginList": ["*"]
     }
     ```
   * Create the target deck named **`Daily`** (this must match `VB_TARGET_DECK`).
   * Quit Anki so the profile is flushed to disk.

2. **Copy the prepared profile into the `anki-headless` `/data` volume**:
   * Start the stack so the named volume is created:
     ```bash
     cd /opt/lexibot
     sudo docker compose up -d
     ```
   * Copy the prepared Anki profile folder (the `User 1` collection directory plus `prefs.db` / add-on folders) into the container's `/data` volume. The exact path depends on the headless image's Anki data root; copy the whole Anki data folder so the profile, add-ons, and `prefs.db` land under `/data`:
     ```bash
     sudo docker cp ./prepared-anki-profile/. lexibot-anki-headless-1:/data/
     sudo docker compose restart anki-headless
     ```
   * Verify AnkiConnect is reachable on the internal network:
     ```bash
     sudo docker exec lexibot-bot-1 python -c "import socket; s = socket.socket(); s.connect(('anki-headless', 8765)); print('Connected!')"
     # Expected output: Connected!
     ```

3. **Debugging aside (optional)**: if you ever need a real GUI surface (e.g. to fix a stuck profile), set `QT_QPA_PLATFORM=vnc` in the `anki-headless` service environment and uncomment the `# ports: ["5900:5900"]` block in `docker-compose.yml`. That exposes a debug VNC surface on port 5900 — **not** for normal operation. In normal operation the container stays headless with no published ports.

---

## 5. Deployment Verification
1. **Health Check Endpoint**:
   * Test the public endpoint: `curl -i https://<your-domain>/healthz` (should return `200 OK` and `{"status":"ok"}`).
2. **Real-time Stepper & Webhook Test**:
   * Open your Telegram bot and send a word.
   * The bot will display a single progress message updating in real-time (`Queue` -> `LLM` -> `TTS` -> `Anki` -> `Added`).
   * For single-word batches, once complete, the message updates to a rich Markdown card preview with `Edit Meaning`, `Regen Examples`, and `Delete Card` inline buttons.
   * For multi-word batches, the message updates to a clean outcome checklist.

---

## 6. AnkiWeb Sync & Client Connection

The self-hosted sync server was removed: the headless Anki profile syncs to **AnkiWeb** (Anki's official servers) using the credentials copied into the profile. Personal devices sync to AnkiWeb normally — there is no `/sync/*` Caddy ingress and no `SYNC_USER1` to configure.

### Connecting Your Personal Device (AnkiMobile / AnkiDroid / Anki Desktop)
1. **Server URL**: leave the sync server at the default AnkiWeb URL (`https://sync.ankiweb.net`). Do **not** point your device at the bot's domain — there is no public sync endpoint.
2. **Credentials**: log in with your AnkiWeb account (the same one the headless profile is authenticated to).
3. **Trigger Sync**: click **Sync** on your personal device. AnkiWeb mediates between your device and the headless profile; cards added by the Telegram bot appear after the headless profile's debounced sync runs.

---

## 7. Troubleshooting & Hard Lessons Learned

### Container Healthchecks and Missing Tools
If `anki-headless` is reported as `unhealthy` by `docker compose ps` even though AnkiConnect is active, check the healthcheck command defined in `docker-compose.yml`:
* The minimal Debian-slim image used for `anki-headless` does not have `nc` (netcat) installed.
* Standard `nc -z localhost 8765` healthcheck commands will fail with command-not-found (exit code 127).
* **Fix**: Use bash's built-in socket check in the container healthcheck configuration:
  ```yaml
  test: ["CMD", "/bin/bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/8765"]
  ```
