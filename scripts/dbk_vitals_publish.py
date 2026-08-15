#!/usr/bin/env python3
"""Publish DBK vital signs as one retained JSON message to MQTT.

Runs on the host: vcgencmd, the SD card and the kernel log are not visible
inside the containers. Values that cannot be determined are reported as
None/"unknown" instead of a guess.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VITALS_URL = os.environ.get("DBK_VITALS_URL", "http://127.0.0.1:8091/api/vitals")
ALBUM_DIR = Path(os.environ.get("DBK_ALBUM_DIR", "/home/sebi/dbk-album/Digi Bilderkalender Ana"))
SYNC_LOG = Path(os.environ.get("DBK_SYNC_LOG", "/home/sebi/immichdl/cron.log"))
SYNC_OK_MARKER = "Cache warm."
TOPIC = os.environ.get("DBK_VITALS_TOPIC", "dbk/vitals")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def host_vitals():
    try:
        with urllib.request.urlopen(VITALS_URL, timeout=8) as res:
            payload = json.load(res)
    except Exception as exc:
        unknown = {"status": "unknown", "error": str(exc)}
        return dict(unknown), dict(unknown)
    return payload.get("throttled") or {"status": "unknown"}, payload.get("disk") or {"status": "unknown"}


def temp_c():
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
    except OSError:
        return None
    try:
        return round(int(raw) / 1000.0, 1)
    except ValueError:
        return None


def uptime_s():
    try:
        return round(float(Path("/proc/uptime").read_text().split()[0]), 1)
    except (OSError, ValueError, IndexError):
        return None


def album():
    result = {"count": None, "size_mb": None, "newest_iso": None, "error": None}
    try:
        files = [p for p in ALBUM_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    except OSError as exc:
        result["error"] = str(exc)
        return result

    total = 0
    newest = 0.0
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        total += st.st_size
        newest = max(newest, st.st_mtime)

    result["count"] = len(files)
    result["size_mb"] = round(total / 1e6, 1)
    result["newest_iso"] = _iso(newest) if newest else None
    return result


def sync_status():
    """The nightly cron run overwrites cron.log, so mtime = last run and the
    script's closing marker decides the outcome."""
    result = {"last_run_iso": None, "result": "unknown", "error": None}
    try:
        text = SYNC_LOG.read_text(errors="replace")
        result["last_run_iso"] = _iso(SYNC_LOG.stat().st_mtime)
    except OSError as exc:
        result["error"] = str(exc)
        return result
    result["result"] = "ok" if SYNC_OK_MARKER in text else "error"
    return result


def kernel_errors():
    result = {"ext4": None, "usb": None, "error": None}
    try:
        proc = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        result["error"] = str(exc)
        return result
    if proc.returncode != 0:
        result["error"] = (proc.stderr or "dmesg failed").strip()
        return result
    log = proc.stdout
    result["ext4"] = len(re.findall(r"EXT4-fs (error|warning)", log))
    result["usb"] = len(re.findall(r"usb \S+: (device descriptor read|device not accepting address|reset .* failed)", log))
    return result


def main():
    host = os.environ.get("MQTT_HOST")
    user = os.environ.get("MQTT_USER")
    password = os.environ.get("MQTT_PASS")
    if not host:
        print("MQTT_HOST missing", file=sys.stderr)
        return 2

    throttled, disk = host_vitals()
    payload = {
        "ts": int(time.time()),
        "iso": _iso(time.time()),
        "uptime_s": uptime_s(),
        "temp_c": temp_c(),
        "throttled": throttled,
        "disk": disk,
        "album": album(),
        "sync": sync_status(),
        "kernel_errors": kernel_errors(),
    }

    cmd = ["mosquitto_pub", "-h", host, "-t", TOPIC, "-r", "-m", json.dumps(payload)]
    if user:
        cmd += ["-u", user]
    if password:
        cmd += ["-P", password]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        print((proc.stderr or "mosquitto_pub failed").strip(), file=sys.stderr)
        return 1
    print(f"published {TOPIC}: {json.dumps(payload)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
