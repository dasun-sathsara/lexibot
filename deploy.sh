#!/usr/bin/env bash
set -euo pipefail

# 1. Determine SSH target
TARGET=""
if [ $# -ge 1 ]; then
    TARGET="$1"
else
    # Try parsing DOMAIN or webhook URL from local .env
    if [ -f .env ]; then
        # Extract DOMAIN from .env
        DOMAIN=$(grep -E "^DOMAIN=" .env | cut -d'=' -f2- || true)
        if [ -n "$DOMAIN" ]; then
            # Resolve DOMAIN to IP
            IP=$(dig +short "$DOMAIN" | tail -n1)
            if [ -n "$IP" ]; then
                TARGET="azureuser@$IP"
                echo "Resolved target from local .env DOMAIN=$DOMAIN to $TARGET"
            fi
        fi
    fi
fi

if [ -z "$TARGET" ]; then
    echo "Usage: $0 <username@ip_or_host>"
    echo "Alternatively, define DOMAIN in your local .env and run this script from the project root."
    exit 1
fi

echo "=== Deploying lexibot to $TARGET ==="

# 2. Check local environment
if [ ! -f .env ]; then
    echo "Error: Local .env file not found. Please create one based on .env.example before deploying."
    exit 1
fi

# 3. Create app directory and set ownership on remote VPS
echo "=== 1. Preparing remote directories ==="
ssh -o StrictHostKeyChecking=no "$TARGET" "sudo mkdir -p /opt/lexibot && sudo chown -R \$(whoami):\$(whoami) /opt/lexibot"

# 4. Sync workspace
echo "=== 2. Syncing local workspace to VPS ==="
rsync -avz \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.mypy_cache/' \
    ./ "$TARGET":/opt/lexibot/

# 5. Run bootstrap
echo "=== 3. Bootstrapping VPS dependencies (swap, docker, ansible) ==="
ssh -o StrictHostKeyChecking=no "$TARGET" "chmod +x /opt/lexibot/deploy/bootstrap.sh && /opt/lexibot/deploy/bootstrap.sh"

# 6. Build and up docker compose
echo "=== 4. Building and launching Docker Compose stack ==="
ssh -o StrictHostKeyChecking=no "$TARGET" "cd /opt/lexibot && sudo docker compose build && sudo docker compose up -d"

# 7. Check container health status
echo "=== 5. Verifying container health ==="
for i in {1..6}; do
    echo "Waiting for services to initialize... (attempt $i/6)"
    sleep 10
    STATUS=$(ssh -o StrictHostKeyChecking=no "$TARGET" "sudo docker ps --format 'table {{.Names}}\t{{.Status}}'")
    echo "$STATUS"
    if echo "$STATUS" | grep -q "healthy" && ! echo "$STATUS" | grep -q "unhealthy" && ! echo "$STATUS" | grep -q "starting"; then
        echo "=== All services are healthy and running! ==="
        exit 0
    fi
done

echo "Warning: Some services may still be starting or failed to become healthy. Please check logs: ssh $TARGET 'cd /opt/lexibot && sudo docker compose logs'"
