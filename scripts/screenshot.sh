#!/usr/bin/env bash
set -euo pipefail

# Save screenshots to ~/temp with timestamp
OUTDIR="$HOME/temp"
mkdir -p "$OUTDIR"
TS="$(date +'%Y-%m-%d_%H-%M-%S')"
OUT="$OUTDIR/screenshot_$TS.png"

# X11 display (most kiosk setups use :0)
export DISPLAY="${DISPLAY:-:0}"

# Use the user's Xauthority cookie (needed when running via SSH)
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

# Take screenshot
scrot "$OUT"

echo "$OUT"
