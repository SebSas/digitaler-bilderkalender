#!/usr/bin/env bash
set -euo pipefail

TS="$(date +%F_%H%M%S)"
BK="/var/backups/dbk-upgrade/$TS"

echo "== DBK pre-upgrade backup to $BK =="
sudo mkdir -p "$BK"

sudo cp -a /boot/firmware/config.txt  "$BK/config.txt"
sudo cp -a /boot/firmware/cmdline.txt "$BK/cmdline.txt"

# systemd units + overrides (full folder is fine, it's small)
sudo tar -C /etc -cpf "$BK/etc_systemd.tar" systemd/system

# your kiosk/autostart
sudo tar -cpf "$BK/openbox_autostart.tar" -C /home/sebi .config/openbox/autostart

# docker compose dirs
sudo tar -cpf "$BK/dbk_docker.tar" -C /home/sebi docker/dbk-api docker/dbk-web

echo "Backup done."
echo "Running apt update/upgrade..."
sudo apt-get update
sudo apt-get -y upgrade

echo "Upgrade done."
echo "Next: reboot + check"
echo "  sudo reboot"
echo "  curl -fsS http://127.0.0.1:8080/api/health ; echo"
