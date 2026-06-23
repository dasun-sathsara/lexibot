# Comprehensive Deployment Guide

This guide outlines the step-by-step process for deploying the **lexibot** application stack onto a self-hosted Linux VPS.

---

## 1. Prerequisites
* **VPS Host**: A virtual private server running Ubuntu 24.04 (or similar modern Debian-based Linux). 
  * **Memory Requirement**: At least **2 GiB of RAM** is highly recommended (e.g. Azure `Standard_B2als_v2` or similar). A 1 GiB instance can be used only if a **2 GiB swap file** is configured to absorb spikes from the Anki QtWebEngine process.
  * **Swap Configuration**:
    ```bash
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile && sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    ```
* **DNS Configuration**: A domain name (e.g. `bot.appledorelabs.dev`) with an **A record** pointing to the public IP of your VPS.
* **Port Availability**:
  * **Port 80 (HTTP)** and **Port 443 (HTTPS)** must be open to the public internet for the Caddy web server (handles webhook + public sync requests).
  * **Port 6080 (VNC over HTTPS)** must be open (at least temporarily) to allow you to configure the headless Anki profile.
  * **Port 22 (SSH)** for admin access.
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
   * `DOMAIN`: Your pointed domain (e.g., `bot.appledorelabs.dev`).
   * `VB_WEBHOOK_BASE_URL`: Set to `https://<your-domain>` (e.g., `https://bot.appledorelabs.dev`).
   * `VB_TELEGRAM_TOKEN`: Real Telegram Bot Token from `@BotFather`.
   * `VB_ALLOWED_IDS`: Your numeric Telegram user ID (comma-separated if multiple).
   * `VB_ADMIN_ID`: Your numeric Telegram user ID for alert notifications.
   * `VB_GEMINI_API_KEYS`: Your Gemini API Key (from Google AI Studio, comma-separated if multiple).
   * `VB_AZURE_SPEECH_KEY`: Your Azure Speech / AI Services key.
   * `VB_AZURE_SPEECH_ENDPOINT`: The Azure region code (e.g. `eastus2`). *Note: For multi-service Cognitive Services keys, this must be the region name (e.g. `eastus2`) instead of the endpoint URL to prevent 401 WebSocket errors.*
   * `SYNC_USER1`: The credentials for the self-hosted sync server in the format `email:password` (e.g., `pabasarax@gmail.com:LDt9FHfwsM5ufFj`).
   * `ANKI_SYNC_USER`: The username portion of `SYNC_USER1` (used to automatically configure the headless client sync).
   * `ANKI_SYNC_PASS`: The password portion of `SYNC_USER1` (used to automatically configure the headless client sync).
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
   * Visit `https://<your-domain>:6080` (or `https://<vps-ip>:6080`) in your web browser.
   * **Chrome/HSTS Bypass**: If your domain uses a TLD like `.dev` (which forces HTTPS), Chrome will block connection to self-signed certificates with no "Proceed (unsafe)" button. You can bypass this by visiting the raw VPS IP address directly, or by clicking anywhere on the background of the warning page on the domain and typing **`thisisunsafe`** blindly on your keyboard.
3. **Log in to Sync Server**:
   * Click **Sync** inside the headless Anki GUI.
   * Log in using the `email` and `password` credentials you defined under `SYNC_USER1` in your `.env`.
4. **Install the AnkiConnect Add-on**:
   * Go to **Tools** -> **Add-ons**.
   * Click **Get Add-ons...** and paste the code: **`2055492159`**.
5. **Create the target Deck**:
   * Click **Create Deck** at the bottom of the Anki GUI and name it **`Daily`**.
6. **Apply AnkiConnect Bind Configuration**:
   * *Note: The deployment setup automatically pre-configures AnkiConnect to listen on `0.0.0.0` inside the volume.*
   * Overwrite/verify the configuration file on the VPS host if needed:
     ```json
     {
         "webBindAddress": "0.0.0.0",
         "webCorsOriginList": ["*"]
     }
     ```
7. **Restart the Headless Server**:
   * Restart the container to apply the config changes and verify that AnkiConnect is now listening on all interfaces inside the container:
     ```bash
     sudo docker compose restart anki-headless
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

---

## 6. Logs Shipping (Axiom)
To ship your Docker stdout logs to Axiom (which offers a generous 500 GB/month free tier):
1. **Create an Axiom Dataset & API Token**:
   * Log in to [Axiom](https://axiom.co/) and create a dataset named `lexibot`.
   * Go to settings and generate an API token with ingest permissions.
2. **Configure Logs Shipping**:
   * You can configure Docker to send logs via standard syslog, or run a lightweight agent like [Vector](https://vector.dev/) on the VPS to tail the Docker JSON log files and ship them directly to Axiom's OTLP/HTTP endpoint.

---

## 7. Public Sync Server Setup & Client Connection
Caddy acts as the public entrypoint and automatically handles SSL termination for the Anki Sync Server.

### Caddy Routing Configuration
The `/sync/*` path is routed internally to the sync server container:
```caddy
	handle /sync/* {
		reverse_proxy anki-sync-server:8080
	}
```

### Connecting Your Personal Device (AnkiMobile / AnkiDroid / Anki Desktop)
To sync your personal devices with the self-hosted sync server:
1. **Server URL Configuration**:
   * Open your Anki client settings (Syncing preferences).
   * Set the self-hosted sync server URL to: `https://bot.appledorelabs.dev/` (include the trailing slash).
2. **Credentials**:
   * Log in using your email and password as defined under `SYNC_USER1` (e.g., `pabasarax@gmail.com` and `LDt9FHfwsM5ufFj`).
3. **Trigger Sync**:
   * Click **Sync** on your personal device. It will authenticate with the server and pull all cards added by the Telegram bot.
