#!/usr/bin/env bash
set -euo pipefail

KIOSK_PROFILE="/home/sebi/.config/chromium-kiosk"
CHROMIUM_BIN="/usr/lib/chromium/chromium"
AUTOSTART="/home/sebi/.config/openbox/autostart"
STACK_SERVICE="dbk-stack.service"

log() { echo "$(date -Is) $*"; }

stop_kiosk_and_chromium() {
  log "Stopping kiosk watchdog + Chromium..."
  pkill -f "sh $AUTOSTART" || true
  pkill -f "$CHROMIUM_BIN" || true
  pkill -f "user-data-dir=$KIOSK_PROFILE" || true

  for _ in {1..20}; do
    if pgrep -f "$CHROMIUM_BIN" >/dev/null 2>&1; then
      sleep 0.25
    else
      break
    fi
  done
}

reset_profile() {
  log "Resetting kiosk profile: $KIOSK_PROFILE"
  rm -rf "$KIOSK_PROFILE"
  mkdir -p "$KIOSK_PROFILE"
}

start_watchdog() {
  log "Relaunching kiosk watchdog (Openbox autostart)..."
  DISPLAY=:0 sh "$AUTOSTART" >/dev/null 2>&1 &
}

fast_reset() {
  stop_kiosk_and_chromium
  reset_profile
  start_watchdog
  log "FAST reset done."
}

full_reset() {
  stop_kiosk_and_chromium
  reset_profile
  log "Restarting DBK stack ($STACK_SERVICE)..."
  sudo systemctl restart "$STACK_SERVICE"
  start_watchdog
  log "FULL reset done."
}

usage() {
  cat <<EOF
Usage:
  $(basename "$0")            # interactive menu
  $(basename "$0") fast       # non-interactive fast reset
  $(basename "$0") full       # non-interactive full reset
EOF
}

choice="${1:-}"

if [[ -z "$choice" ]]; then
  echo "DBK reset:"
  echo "  1) FAST  (Chromium + profile + watchdog)"
  echo "  2) FULL  (FAST + restart $STACK_SERVICE)"
  echo -n "Select [1/2] (default 1): "
  read -r sel || true
  case "${sel:-1}" in
    1) choice="fast" ;;
    2) choice="full" ;;
    *) choice="fast" ;;
  esac
fi

case "$choice" in
  fast) fast_reset ;;
  full) full_reset ;;
  -h|--help|help) usage ;;
  *) echo "Unknown option: $choice"; usage; exit 1 ;;
esac