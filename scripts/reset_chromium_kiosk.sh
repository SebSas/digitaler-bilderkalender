#!/usr/bin/env bash
set -euo pipefail

KIOSK_PROFILE="/home/sebi/.config/chromium-kiosk"
CHROMIUM_BIN="/usr/lib/chromium/chromium"
AUTOSTART="/home/sebi/.config/openbox/autostart"

log() { echo "$(date -Is) $*"; }

log "Stopping kiosk watchdog + Chromium..."
pkill -f "sh $AUTOSTART" || true
pkill -f "$CHROMIUM_BIN" || true
pkill -f "user-data-dir=$KIOSK_PROFILE" || true

# Wait a moment for processes to exit
for _ in {1..20}; do
  if pgrep -f "$CHROMIUM_BIN" >/dev/null 2>&1; then
    sleep 0.25
  else
    break
  fi
done

log "Resetting kiosk profile: $KIOSK_PROFILE"
rm -rf "$KIOSK_PROFILE"
mkdir -p "$KIOSK_PROFILE"

log "Restarting DBK stack..."
sudo systemctl restart dbk-stack.service

log "Relaunching kiosk watchdog (Openbox autostart)..."
DISPLAY=:0 sh "$AUTOSTART" >/dev/null 2>&1 &

log "Done."