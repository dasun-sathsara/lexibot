#!/usr/bin/env bash
set -euo pipefail

echo "=== 1. Creating Swap Space (2 GiB) ==="
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "Swap space configured successfully."
else
    echo "Swap file already exists. Skipping."
fi

echo "=== 2. Updating System & Installing Ansible ==="
sudo apt-get update
sudo apt-get install -y software-properties-common
sudo apt-add-repository --yes --update ppa:ansible/ansible
sudo apt-get install -y ansible git curl ca-certificates

echo "=== 3. Creating App Directory ==="
sudo mkdir -p /opt/lexibot
sudo chown -R azureuser:azureuser /opt/lexibot

echo "=== 4. Running Ansible Playbook ==="
# We run the playbook locally on the VPS
# Note: The playbook itself clones the repository into /opt/lexibot.
sudo ansible-playbook -i localhost, -c local /opt/lexibot/deploy/ansible/playbook.yml || {
    echo "Ansible playbook failed. Let's clone manually and retry."
    if [ ! -d /opt/lexibot/.git ]; then
        git clone https://github.com/dasun-sathsara/lexibot.git /opt/lexibot
    fi
    sudo ansible-playbook -i localhost, -c local /opt/lexibot/deploy/ansible/playbook.yml
}

echo "=== Bootstrap Completed ==="
