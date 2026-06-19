# Comprehensive Deployment Guide

This guide outlines the step-by-step process for deploying the **lexibot** application stack onto a self-hosted Linux VPS.

---

## 1. Prerequisites
* **VPS Host**: A virtual private server running Ubuntu 24.04 (or similar modern Debian-based Linux).
* **DNS Configuration**: A domain name (e.g. `appledorelabs.dev`) with an **A record** pointing to the public IP of your VPS.
* **Port Availability**:
  * **Port 80 (HTTP)** and **Port 443 (HTTPS)** must be open to the public internet for the Caddy web server (and Let's Encrypt ACME challenges).
  * **Port 6080 (VNC over HTTPS)** must be open (at least temporarily) to allow you to configure the headless Anki profile.

---

## 2. Server Provisioning
The project includes an Ansible playbook to automate server setup (Docker Engine + Docker Compose plugin).

1. Install Ansible on your local machine (or on the VPS itself).
2. Run the playbook to provision the VPS and clone the repository to `/opt/lexibot`:
   ```bash
   sudo ansible-playbook -i localhost, -c local deploy/ansible/playbook.yml
   ```
3. Verify that Docker and Compose are fully operational on the VPS:
   ```bash
   docker --version
   docker compose version
   ```

---

## 3. Environment & Secrets Configuration
Create and fill the `/opt/lexibot/.env` file on the VPS:

1. Copy the example template:
   ```bash
   cp /opt/lexibot/.env.example /opt/lexibot/.env
   ```
2. Open `/opt/lexibot/.env` and configure the following variables:
   * `DOMAIN`: Your pointed domain (e.g., `appledorelabs.dev`).
   * `VB_WEBHOOK_BASE_URL`: Set to `https://<your-domain>` (e.g., `https://appledorelabs.dev`).
   * `VB_TELEGRAM_TOKEN`: Real Telegram Bot Token from `@BotFather`.
   * `VB_ALLOWED_IDS`: Your numeric Telegram user ID (comma-separated if multiple).
   * `VB_ADMIN_ID`: Your numeric Telegram user ID for alert notifications.
   * `VB_GEMINI_API_KEYS`: Your Gemini API Key (from Google AI Studio).
   * `VB_AZURE_SPEECH_KEY`: Your Azure Speech / AI Services key.
   * `VB_AZURE_SPEECH_ENDPOINT`: The Azure region code (e.g. `eastus2`). *Note: For multi-service Cognitive Services keys, this must be the region name (e.g. `eastus2`) instead of the endpoint URL to prevent 401 WebSocket errors.*
   * `SYNC_USER1`: The credentials for the self-hosted sync server in the format `email:password` (e.g., `evondexmail@gmail.com:zP5X36e32BPTGin`).
   * `VB_DATABASE_URL`: Set to `sqlite+aiosqlite:///app/data/vocab.db` (enables database persistence in the mounted `bot-data` volume).
   * `VB_WEBHOOK_SECRET`: A secure random hex string for securing the webhook endpoint (e.g. generated via `openssl rand -hex 16`).

---

## 4. First-Time Headless Anki Setup
Because Anki requires one-time sync server authentication and profile bootstrapping, you must complete these manual configuration steps in the headless desktop:

1. **Start the Stack**:
   ```bash
   cd /opt/lexibot
   sudo docker compose up -d
   ```
2. **Access the VNC Web Desktop**:
   * Visit `https://<your-domain>:6080` in your web browser.
   * **Chrome/HSTS Bypass**: If your domain uses a TLD like `.dev` (which forces HTTPS), Chrome will block connection to self-signed certificates with no "Proceed (unsafe)" button. Bypass this by clicking anywhere on the background of the warning page and typing **`thisisunsafe`** on your keyboard.
3. **Log in to Sync Server**:
   * Click **Sync** inside the headless Anki GUI.
   * Log in using the `email` and `password` credentials you defined under `SYNC_USER1` in your `.env`.
4. **Install the AnkiConnect Add-on**:
   * Go to **Tools** -> **Add-ons**.
   * Click **Get Add-ons...** and paste the code: **`2055492159`**.
5. **Create the target Deck**:
   * Click **Create Deck** at the bottom of the Anki GUI and name it **`Daily`**.
6. **Reconfigure AnkiConnect Bind Address**:
   * By default, AnkiConnect only listens on localhost (`127.0.0.1:8765`), which prevents the worker container from reaching it.
   * On the VPS host, open the add-on configuration file:
     ```bash
     sudo nano /var/lib/docker/volumes/lexibot_anki-profile/_data/.local/share/Anki2/addons21/2055492159/config.json
     ```
   * Modify the binding properties to allow connections from all interfaces:
     ```json
     {
         "webBindAddress": "0.0.0.0",
         "webCorsOriginList": ["*"]
     }
     ```
7. **Restart the Headless Server**:
   * Exit Anki in the VNC window or restart the container:
     ```bash
     sudo docker compose restart anki-headless
     ```
   * Verify that AnkiConnect is now listening on all interfaces inside the container:
     ```bash
     sudo docker exec lexibot-anki-headless-1 ss -tuln | grep 8765
     # Expected output: tcp LISTEN 0 5 0.0.0.0:8765 ...
     ```

---

## 5. Deployment Verification
1. **Health Check Endpoint**:
   * Test the public endpoint: `curl -i https://<your-domain>/healthz` (should return `200 OK` and `{"status":"ok"}`).
2. **Real-time Stepper & Webhook Test**:
   * Open your Telegram bot and send a word.
   * The bot will display a single progress message updating in real-time (`Queue` -> `LLM` -> `TTS` -> `Anki` -> `Added`).
   * For single-word batches, once complete, the message updates to a rich Markdown card preview with `Edit Meaning`, `Regen Examples`, and `Delete Card` inline buttons.
   * For multi-word batches, the message updates to a clean outcome checklist.
