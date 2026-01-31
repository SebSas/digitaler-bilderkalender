#!/usr/bin/env bash
set -euo pipefail

PROFILE_DIR="/home/sebi/.config/chromium-kiosk/Default"
PREFS_FILE="$PROFILE_DIR/Preferences"

mkdir -p "$PROFILE_DIR"

python - <<'PY'
import json
from pathlib import Path

prefs_path = Path("/home/sebi/.config/chromium-kiosk/Default/Preferences")

prefs = {}
if prefs_path.exists():
    try:
        prefs = json.loads(prefs_path.read_text())
    except Exception:
        prefs = {}

prefs.setdefault("translate", {})["enabled"] = False
prefs.setdefault("intl", {})["accept_languages"] = "de,de-DE"

prefs_path.write_text(json.dumps(prefs, indent=2, sort_keys=True))
PY

chmod 644 "$PREFS_FILE" || true

echo "Chromium translate disabled in kiosk profile prefs."
