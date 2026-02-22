#!/usr/bin/env bash
set -euo pipefail

# Log to journald
exec 1> >(systemd-cat -t dbk-postboot-check) 2>&1
echo "==== $(date -Is) dbk_postboot_check start ===="

HEALTH_URL="http://127.0.0.1:8080/api/health"
export DISPLAY=:0

check_backend() {
  if curl -fsS --connect-timeout 1 --max-time 2 "$HEALTH_URL" >/dev/null; then
    echo "$(date -Is) backend: OK"
    return 0
  else
    echo "$(date -Is) backend: FAIL"
    return 1
  fi
}

check_screen_dark_pct() {
  local out="/tmp/dbk-screen.png"

  if ! ls -S /tmp/.X11-unix/X0 >/dev/null 2>&1; then
    echo "$(date -Is) X socket missing (/tmp/.X11-unix/X0)"
    echo "100.00"
    return 0
  fi

  command -v import >/dev/null 2>&1 || { echo "$(date -Is) imagemagick import missing"; echo "100.00"; return 0; }
  python3 -c "import PIL" >/dev/null 2>&1 || { echo "$(date -Is) python pillow missing (python3-pil)"; echo "100.00"; return 0; }

  import -window root "$out" || { echo "$(date -Is) screenshot failed"; echo "100.00"; return 0; }

  python3 - <<'PY'
from PIL import Image
img = Image.open("/tmp/dbk-screen.png").convert("RGB")
w,h = img.size
px = img.getdata()
dark = sum(1 for r,g,b in px if r<10 and g<10 and b<10)
print(round(dark/(w*h)*100, 2))
PY
}

is_black() {
  # returns 0 if black-ish, 1 otherwise
  local pct="$1"
  python3 - <<PY
d=float("$pct")
import sys
sys.exit(0 if d >= 98.0 else 1)
PY
}

# --- Run checks ---
check_backend || true

dark_pct="$(check_screen_dark_pct)"
echo "$(date -Is) screen dark_pixels_%=${dark_pct}"

if python3 - <<PY
d=float("$dark_pct")
import sys
sys.exit(0 if d < 10.0 else 1)
PY
then
  echo "$(date -Is) display: OK (sanity floor: dark<10%)"
  exit 0
fi

if is_black "$dark_pct"; then
  echo "$(date -Is) display: BLACK detected -> attempting 1x recovery (restart getty@tty1)"
  if sudo /bin/systemctl restart getty@tty1; then
    sleep 10
    dark_pct2="$(check_screen_dark_pct)"
    echo "$(date -Is) screen(after-recovery) dark_pixels_%=${dark_pct2}"

    if is_black "$dark_pct2"; then
      echo "$(date -Is) display: STILL BLACK after recovery (logged only)"
      exit 0
    else
      echo "$(date -Is) display: OK after recovery"
      exit 0
    fi
  else
    echo "$(date -Is) recovery: FAILED to restart getty@tty1 (sudoers?)"
    exit 0
  fi
else
  echo "$(date -Is) display: OK"
  exit 0
fi
