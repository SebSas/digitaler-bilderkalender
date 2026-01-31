#!/usr/bin/env bash
set -euo pipefail

KIOSK_PROFILE="/home/sebi/.config/chromium-kiosk"

# Stop any running Chromium processes (kiosk will auto-restart via autostart).
pkill -x chromium || true
pkill -x chromium-browser || true
sleep 1

# Remove the kiosk profile to clear all caches and state.
rm -rf "$KIOSK_PROFILE"
mkdir -p "$KIOSK_PROFILE"

echo "Chromium kiosk profile reset. Autostart should relaunch Chromium shortly."
