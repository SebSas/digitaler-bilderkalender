#!/usr/bin/env bash
# HDMI audio test for the display speakers (internet radio idea).
# Starts a 440 Hz test tone at volume 0 — keys: [+] louder, [-] quieter, [q] quit.
#
# The vc4hdmi cards expose no hardware volume control, so this script sets up
# an ALSA softvol PCM ("DBK Test Volume", persisted in ~/.asoundrc) and always
# starts at 0% so nothing blasts unexpectedly.
#
# Usage: dbk_audio_test.sh [vc4hdmi0|vc4hdmi1]   (default: auto-detect via DRM)
set -euo pipefail

STEP=5

detect_card() {
  # Map the connected HDMI port to its audio card (HDMI-A-1 -> vc4hdmi0, A-2 -> vc4hdmi1)
  local f status n
  for n in 1 2; do
    for f in /sys/class/drm/card*-HDMI-A-"$n"/status; do
      [[ -f "$f" ]] || continue
      status=$(cat "$f")
      if [[ "$status" == "connected" ]]; then
        echo "vc4hdmi$((n - 1))"
        return 0
      fi
    done
  done
  echo "vc4hdmi0"
}

CARD="${1:-$(detect_card)}"
case "$CARD" in
  vc4hdmi0) PCM="dbk_test_vol0" ;;
  vc4hdmi1) PCM="dbk_test_vol1" ;;
  *) echo "Unknown card: $CARD (expected vc4hdmi0 or vc4hdmi1)" >&2; exit 1 ;;
esac

# Register the softvol PCMs once (append-only, marker-guarded)
if ! grep -q "dbk_test_vol0" "$HOME/.asoundrc" 2>/dev/null; then
  cat >> "$HOME/.asoundrc" <<'EOF'
# --- DBK audio test (softvol for vc4hdmi, added by dbk_audio_test.sh) ---
pcm.dbk_test_vol0 {
  type softvol
  slave.pcm "plughw:vc4hdmi0"
  control { name "DBK Test Volume"; card vc4hdmi0 }
}
pcm.dbk_test_vol1 {
  type softvol
  slave.pcm "plughw:vc4hdmi1"
  control { name "DBK Test Volume"; card vc4hdmi1 }
}
# --- end DBK audio test ---
EOF
  echo "softvol PCMs registered in ~/.asoundrc"
fi

vol=0
set_vol() { amixer -q -c "$CARD" sset "DBK Test" "${vol}%" 2>/dev/null || true; }

# Prime with 1s of silence so ALSA creates the softvol control, then force 0%
# BEFORE any audible tone starts (softvol controls default to full volume).
aplay -q -D "$PCM" -f S16_LE -r 48000 -c 2 -d 1 /dev/zero 2>/dev/null || {
  echo "Priming failed — is the display connected to $CARD?" >&2
  exit 1
}
set_vol

speaker-test -D "$PCM" -c 2 -t sine -f 440 >/dev/null 2>&1 &
TONE_PID=$!
trap 'kill "$TONE_PID" 2>/dev/null || true; wait "$TONE_PID" 2>/dev/null || true' EXIT

echo "Testton läuft auf $CARD (PCM $PCM), Lautstärke: ${vol}%"
echo "Tasten: [+] lauter (+${STEP}%), [-] leiser, [q] beenden"

while kill -0 "$TONE_PID" 2>/dev/null; do
  IFS= read -rsn1 key || break
  case "$key" in
    +|=) vol=$(( vol + STEP > 100 ? 100 : vol + STEP )); set_vol; echo "Lautstärke: ${vol}%" ;;
    -|_) vol=$(( vol - STEP < 0 ? 0 : vol - STEP )); set_vol; echo "Lautstärke: ${vol}%" ;;
    q|Q) break ;;
  esac
done

echo "Beendet."
