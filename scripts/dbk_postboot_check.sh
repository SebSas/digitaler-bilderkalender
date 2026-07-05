#!/usr/bin/env bash
set -euo pipefail

exec 1> >(systemd-cat -t dbk-postboot-check) 2>&1
echo "==== $(date -Is) dbk_postboot_check start ===="

HEALTH_URL="http://127.0.0.1:8080/api/health"
export DISPLAY=:0

# Wait settings
WAIT_MAX=180     # seconds
SLEEP_STEP=3

# Screenshot settings
SHOT="/tmp/dbk-screen.png"
IMPORT_TIMEOUT=5 # seconds

check_backend() {
  curl -fsS --connect-timeout 1 --max-time 2 "$HEALTH_URL" >/dev/null 2>&1
}

x_ready() {
  test -S /tmp/.X11-unix/X0
}

take_screenshot() {
  # returns 0 if screenshot created
  command -v import >/dev/null 2>&1 || return 1
  timeout "${IMPORT_TIMEOUT}s" import -window root "$SHOT" >/dev/null 2>&1
}

dark_pct() {
  python3 - <<'PY'
from PIL import Image
img = Image.open("/tmp/dbk-screen.png").convert("RGB")
w,h = img.size
px = img.getdata()
dark = sum(1 for r,g,b in px if r<10 and g<10 and b<10)
print(round(dark/(w*h)*100, 2))
PY
}

is_blackish() {
  local pct="$1"
  python3 - <<PY
d=float("$pct")
import sys
sys.exit(0 if d >= 98.0 else 1)
PY
}

# --- Phase 1: wait for backend + X (up to WAIT_MAX) ---
t=0
while [ "$t" -lt "$WAIT_MAX" ]; do
  b="FAIL"; x="NO"
  check_backend && b="OK"
  x_ready && x="YES"
  echo "$(date -Is) waiting: backend=$b X=$x t=${t}s"

  if [ "$b" = "OK" ] && [ "$x" = "YES" ]; then
    break
  fi
  sleep "$SLEEP_STEP"
  t=$((t+SLEEP_STEP))
done

# Backend status (final)
if check_backend; then
  echo "$(date -Is) backend: OK"
else
  echo "$(date -Is) backend: FAIL (continuing with display check if possible)"
fi

if ! x_ready; then
  echo "$(date -Is) X not ready -> skip display check (no recovery), exit 0"
  exit 0
fi

# --- Phase 2: screenshot with timeout ---
if ! python3 -c "import PIL" >/dev/null 2>&1; then
  echo "$(date -Is) python pillow missing (python3-pil) -> skip display check, exit 0"
  exit 0
fi

if ! take_screenshot; then
  echo "$(date -Is) screenshot failed or timed out -> skip recovery, exit 0"
  exit 0
fi

pct="$(dark_pct)"
echo "$(date -Is) screen dark_pixels_%=$pct"

if is_blackish "$pct"; then
  echo "$(date -Is) display: BLACK detected -> attempting 1x recovery (restart getty@tty1)"
  sudo /bin/systemctl restart getty@tty1 || true
  sleep 10

  # Try again (but never hang)
  if take_screenshot; then
    pct2="$(dark_pct)"
    echo "$(date -Is) screen(after-recovery) dark_pixels_%=$pct2"
    if is_blackish "$pct2"; then
      echo "$(date -Is) display: STILL BLACK after recovery (logged only)"
    else
      echo "$(date -Is) display: OK after recovery"
    fi
  else
    echo "$(date -Is) screenshot(after-recovery) failed/timed out"
  fi
else
  echo "$(date -Is) display: OK"
fi

exit 0
