#!/usr/bin/env bash
# Delay the end of the Plymouth splash until the DBK backend is ready, showing
# progress messages on the splash. Runs as ExecStartPre of plymouth-quit.service
# (as root, see /etc/systemd/system/plymouth-quit.service.d/wait-backend.conf):
# the splash quits right after this script returns, then getty/X/kiosk start.

HEALTH="http://127.0.0.1:8080/api/health"
IMAGES="http://127.0.0.1:8080/api/images"
TIMEOUT_S=180

say() {
  plymouth display-message --text="$1" 2>/dev/null || true
}

start=$(date +%s)
say "Bilderdienst wird gestartet ..."

until curl -fsS --connect-timeout 2 --max-time 5 "$HEALTH" >/dev/null 2>&1 \
  && curl -fsS --connect-timeout 2 --max-time 5 "$IMAGES" | head -c 1 | grep -q '\['; do
  elapsed=$(( $(date +%s) - start ))
  if [ "$elapsed" -ge "$TIMEOUT_S" ]; then
    # Never block the boot forever: the kiosk waiting loop takes over from here.
    say "Bilderdienst nicht erreichbar - Anzeige startet trotzdem"
    sleep 2
    break
  fi
  say "Bilderdienst wird gestartet ... (${elapsed}s)"
  sleep 3
done

exit 0
