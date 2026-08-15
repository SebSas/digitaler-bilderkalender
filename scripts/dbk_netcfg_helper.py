#!/usr/bin/env python3
"""Host-seitiger Netzwerk-Helfer für den digitalen Bilderkalender.

Der Container kann NetworkManager nicht bedienen (kein D-Bus, kein nmcli),
deshalb läuft die WLAN-Einrichtung hier auf dem Host.
"""

import ipaddress
import json
import os
import re
import secrets
import string
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WIFI_DEV = "wlan0"
HOTSPOT_CON = "dbk-hotspot"
HOTSPOT_SSID = "Bilderkalender-Setup"
HOTSPOT_TIMEOUT = 15 * 60
CONNECT_TIMEOUT = 45
API_PORT = 8091
PORTAL_PORT = 80
STATE_DIR = "/run/dbk-netcfg"
STATE_FILE = os.path.join(STATE_DIR, "state.json")

ALLOWED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("10.42.0.0/16"),
]

_lock = threading.Lock()
_state = {
    "phase": "idle",
    "hotspot": None,
    "message": "",
    "target_ssid": "",
    "updated": 0,
}
_scan_cache = {"at": 0.0, "networks": []}
_hotspot_deadline = None


def nmcli(*args, timeout=60):
    return subprocess.run(
        ["nmcli", *args], capture_output=True, text=True, timeout=timeout
    )


def tailscale_status():
    result = {
        "status": "unavailable",
        "backend_state": None,
        "online": None,
        "hostname": None,
        "ips": [],
        "error": None,
    }
    try:
        res = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=8,
        )
    except FileNotFoundError:
        result["error"] = "tailscale cli not installed on host"
        return result
    except subprocess.TimeoutExpired:
        result["error"] = "tailscale status timeout"
        return result

    if res.returncode != 0:
        result["error"] = (res.stderr or res.stdout).strip()[:300]
        return result

    try:
        payload = json.loads(res.stdout)
    except ValueError:
        result["error"] = "cannot parse tailscale status json"
        return result

    self_data = payload.get("Self") if isinstance(payload.get("Self"), dict) else {}
    ips = self_data.get("TailscaleIPs")
    result["backend_state"] = payload.get("BackendState")
    result["online"] = self_data.get("Online")
    result["hostname"] = self_data.get("HostName")
    result["ips"] = ips if isinstance(ips, list) else []
    result["status"] = "connected" if result["backend_state"] == "Running" else "disconnected"
    return result


def default_route_iface():
    try:
        with open("/proc/net/route") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        cols = line.split()
        if len(cols) >= 4 and cols[1] == "00000000":
            return cols[0]
    return None


THROTTLE_BITS = {
    "undervoltage": 0,
    "freq_capped": 1,
    "throttled": 2,
    "soft_temp_limit": 3,
}
DISK_WARN_PCT = 80.0
DISK_CRIT_PCT = 90.0


def throttled_status():
    """Decode `vcgencmd get_throttled`. Report "unknown" rather than guessing."""
    result = {
        "status": "unknown",
        "raw": None,
        "hex": None,
        "now": {},
        "since_boot": {},
        "error": None,
    }
    try:
        proc = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5
        )
    except Exception as exc:
        result["error"] = str(exc)
        return result

    match = re.search(r"throttled=0x([0-9a-fA-F]+)", proc.stdout or "")
    if proc.returncode != 0 or not match:
        result["error"] = (proc.stderr or proc.stdout or "vcgencmd ohne Ergebnis").strip()
        return result

    value = int(match.group(1), 16)
    result["status"] = "ok"
    result["raw"] = value
    result["hex"] = "0x%x" % value
    for name, bit in THROTTLE_BITS.items():
        result["now"][name] = bool(value & (1 << bit))
        result["since_boot"][name] = bool(value & (1 << (bit + 16)))
    return result


def disk_status(path="/"):
    result = {"status": "unknown", "error": None}
    try:
        st = os.statvfs(path)
    except OSError as exc:
        result["error"] = str(exc)
        return result

    total = st.f_blocks * st.f_frsize
    used = total - st.f_bfree * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used_pct = round(used / total * 100, 1) if total else None
    level = "unknown"
    if used_pct is not None:
        level = "critical" if used_pct >= DISK_CRIT_PCT else (
            "warn" if used_pct >= DISK_WARN_PCT else "ok"
        )
    result.update({
        "status": "ok",
        "total_gb": round(total / 1e9, 1),
        "used_gb": round(used / 1e9, 1),
        "free_gb": round(free / 1e9, 1),
        "used_pct": used_pct,
        "level": level,
    })
    return result


def vitals():
    return {
        "throttled": throttled_status(),
        "disk": disk_status(),
        "ts": int(time.time()),
    }


def set_state(**kwargs):
    with _lock:
        _state.update(kwargs)
        _state["updated"] = int(time.time())
        snapshot = dict(_state)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(snapshot, fh)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def wifi_status():
    res = nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device")
    dev_state, dev_con = "unknown", ""
    for line in res.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[0] == WIFI_DEV:
            dev_state, dev_con = parts[2], parts[3]
            break

    addr = ""
    res = nmcli("-t", "-f", "IP4.ADDRESS", "device", "show", WIFI_DEV)
    for line in res.stdout.splitlines():
        if line.startswith("IP4.ADDRESS") and ":" in line:
            addr = line.split(":", 1)[1].strip()
            break

    ssid = ""
    res = nmcli("-t", "-f", "ACTIVE,SSID", "device", "wifi", "list", "ifname", WIFI_DEV)
    for line in res.stdout.splitlines():
        if line.startswith("yes:"):
            ssid = line.split(":", 1)[1].strip()
            break

    hotspot_active = dev_con == HOTSPOT_CON
    connected = dev_state == "connected" and not hotspot_active

    with _lock:
        phase = _state["phase"]
        message = _state["message"]
        hotspot_info = _state["hotspot"]

    return {
        "device": WIFI_DEV,
        "state": dev_state,
        "connection": dev_con,
        "ssid": ssid,
        "address": addr,
        "connected": connected,
        "hotspot_active": hotspot_active,
        "hotspot": hotspot_info if hotspot_active else None,
        "phase": phase,
        "message": message,
        "needs_setup": not connected and not hotspot_active,
    }


def scan_networks(force=False):
    if not force and time.time() - _scan_cache["at"] < 30:
        return _scan_cache["networks"]

    res = nmcli(
        "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"
    )
    seen, networks = set(), []
    for line in res.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 2 or not parts[0] or parts[0] in seen:
            continue
        seen.add(parts[0])
        networks.append(
            {
                "ssid": parts[0],
                "signal": int(parts[1]) if parts[1].isdigit() else 0,
                "security": parts[2] if len(parts) > 2 else "",
            }
        )
    networks.sort(key=lambda n: n["signal"], reverse=True)
    _scan_cache["at"] = time.time()
    _scan_cache["networks"] = networks
    return networks


def wifi_qr_payload(ssid, psk):
    def esc(value):
        return re.sub(r'([\\;,:"])', r"\\\1", value)

    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(psk)};;"


def qr_svg(payload):
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=14)
    from io import BytesIO

    buf = BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def start_hotspot():
    global _hotspot_deadline

    # Neu aufsetzen würfelt ein neues Passwort und wirft ein bereits verbundenes
    # Handy raus — bei laufendem Hotspot nur die Frist verlängern.
    status = wifi_status()
    if status["hotspot_active"] and status["hotspot"]:
        _hotspot_deadline = time.time() + HOTSPOT_TIMEOUT
        return status["hotspot"]

    scan_networks(force=True)

    psk = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    nmcli("connection", "delete", HOTSPOT_CON)
    res = nmcli(
        "device", "wifi", "hotspot",
        "ifname", WIFI_DEV,
        "con-name", HOTSPOT_CON,
        "ssid", HOTSPOT_SSID,
        "password", psk,
    )
    if res.returncode != 0:
        set_state(phase="error", message=f"Hotspot fehlgeschlagen: {res.stderr.strip()}")
        return None

    info = {"ssid": HOTSPOT_SSID, "psk": psk, "qr": wifi_qr_payload(HOTSPOT_SSID, psk)}
    _hotspot_deadline = time.time() + HOTSPOT_TIMEOUT
    set_state(phase="hotspot", hotspot=info, message="Hotspot aktiv — QR-Code scannen")
    return info


def stop_hotspot():
    global _hotspot_deadline
    _hotspot_deadline = None
    nmcli("connection", "down", HOTSPOT_CON)
    nmcli("connection", "delete", HOTSPOT_CON)
    set_state(phase="idle", hotspot=None, message="")


def connect_worker(ssid, psk):
    set_state(phase="connecting", hotspot=None, target_ssid=ssid,
              message=f"Verbinde mit {ssid} …")
    stop_hotspot()
    set_state(phase="connecting", target_ssid=ssid, message=f"Verbinde mit {ssid} …")

    args = ["device", "wifi", "connect", ssid, "ifname", WIFI_DEV]
    if psk:
        args += ["password", psk]
    res = nmcli(*args, timeout=CONNECT_TIMEOUT + 15)

    # Nur die Ziel-SSID zählt: "irgendein WLAN verbunden" wäre auch dann wahr, wenn
    # das alte Netz noch steht und die neuen Daten gar nicht greifen.
    deadline = time.time() + CONNECT_TIMEOUT
    while time.time() < deadline:
        status = wifi_status()
        if status["connected"] and status["ssid"] == ssid:
            set_state(phase="connected", target_ssid=ssid,
                      message=f"Verbunden mit {ssid}")
            return
        time.sleep(2)

    reason = res.stderr.strip() or "Zeitüberschreitung"
    set_state(phase="failed", target_ssid=ssid,
              message=f"Verbindung fehlgeschlagen: {reason}")
    start_hotspot()
    set_state(phase="hotspot",
              message=f"Verbindung mit {ssid} fehlgeschlagen — bitte erneut einrichten")


def hotspot_reaper():
    while True:
        time.sleep(10)
        if _hotspot_deadline and time.time() > _hotspot_deadline:
            if wifi_status()["hotspot_active"]:
                stop_hotspot()
                set_state(phase="idle", message="Hotspot nach Zeitablauf beendet")


SETUP_PAGE = """<!DOCTYPE html>
<html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bilderkalender — WLAN einrichten</title>
<style>
 body{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:24px;background:#111;color:#eee}
 h1{font-size:1.3rem;margin:0 0 4px}
 p.sub{color:#999;margin:0 0 24px;font-size:.9rem}
 label{display:block;margin:16px 0 6px;font-size:.9rem;color:#bbb}
 input,select{width:100%;box-sizing:border-box;padding:14px;font-size:1rem;border-radius:10px;
   border:1px solid #444;background:#1c1c1c;color:#eee}
 button{width:100%;margin-top:24px;padding:16px;font-size:1.05rem;font-weight:600;
   border:0;border-radius:10px;background:#2d7dd2;color:#fff}
 button:disabled{background:#444}
 #msg{margin-top:20px;padding:14px;border-radius:10px;background:#1c1c1c;display:none}
</style></head><body>
<h1>WLAN einrichten</h1>
<p class="sub">Bilderkalender</p>
<label for="ssid">Netzwerk</label>
<select id="ssid"></select>
<label for="manual">oder Name manuell eingeben</label>
<input id="manual" autocapitalize="none" autocorrect="off" placeholder="WLAN-Name">
<label for="psk">Passwort</label>
<input id="psk" type="password" autocapitalize="none" autocorrect="off">
<button id="go">Verbinden</button>
<div id="msg"></div>
<script>
const msg=document.getElementById('msg');
fetch('/api/scan').then(r=>r.json()).then(d=>{
  const sel=document.getElementById('ssid');
  sel.innerHTML='<option value="">— bitte wählen —</option>';
  d.networks.forEach(n=>{
    const o=document.createElement('option');
    o.value=n.ssid;o.textContent=n.ssid+'  ('+n.signal+'%)';sel.appendChild(o);
  });
}).catch(()=>{});
document.getElementById('go').onclick=()=>{
  const ssid=document.getElementById('manual').value.trim()||document.getElementById('ssid').value;
  const psk=document.getElementById('psk').value;
  if(!ssid){msg.style.display='block';msg.textContent='Bitte ein Netzwerk wählen.';return;}
  document.getElementById('go').disabled=true;
  fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ssid:ssid,psk:psk})}).then(()=>{
    msg.style.display='block';
    msg.innerHTML='<b>Daten übernommen.</b><br>Das Gerät schaltet jetzt um. '+
      'Diese Seite verliert gleich die Verbindung — das Ergebnis erscheint '+
      'auf dem Bildschirm des Bilderkalenders.';
  });
};
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "dbk-netcfg"

    def log_message(self, *args):
        pass

    def _allowed(self):
        try:
            addr = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(addr in net for net in ALLOWED_NETS)

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def do_GET(self):
        if not self._allowed():
            self._json(403, {"error": "forbidden"})
            return

        path = self.path.split("?")[0]

        if path in ("/api/status", "/status"):
            self._json(200, wifi_status())
        elif path in ("/api/tailscale", "/tailscale"):
            info = tailscale_status()
            info["default_route_iface"] = default_route_iface()
            self._json(200, info)
        elif path in ("/api/vitals", "/vitals"):
            self._json(200, vitals())
        elif path in ("/api/scan", "/scan"):
            self._json(200, {"networks": scan_networks()})
        elif path == "/api/qr.svg":
            query = urllib.parse.parse_qs(self.path.partition("?")[2])
            data = (query.get("data") or [""])[0]
            if not data:
                self._json(400, {"error": "data fehlt"})
                return
            try:
                self._send(200, qr_svg(data), "image/svg+xml")
            except Exception as exc:
                self._json(500, {"error": str(exc)})
        elif path == "/api/hotspot/qr.svg":
            with _lock:
                info = _state["hotspot"]
            if not info:
                self._json(409, {"error": "kein Hotspot aktiv"})
                return
            try:
                self._send(200, qr_svg(info["qr"]), "image/svg+xml")
            except Exception as exc:
                self._json(500, {"error": str(exc)})
        elif path in ("/", "/setup", "/index.html"):
            self._send(200, SETUP_PAGE, "text/html; charset=utf-8")
        elif path in ("/hotspot-detect.html", "/generate_204", "/ncsi.txt",
                      "/connecttest.txt", "/success.txt"):
            self._send(200, SETUP_PAGE, "text/html; charset=utf-8")
        else:
            self._send(302, b"", "text/plain", {"Location": "http://10.42.0.1/setup"})

    def do_POST(self):
        if not self._allowed():
            self._json(403, {"error": "forbidden"})
            return

        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}

        if path == "/api/hotspot/start":
            info = start_hotspot()
            if not info:
                self._json(500, wifi_status())
                return
            self._json(200, {"ssid": info["ssid"], "psk": info["psk"], "qr": info["qr"]})
        elif path == "/api/hotspot/stop":
            stop_hotspot()
            self._json(200, wifi_status())
        elif path in ("/api/connect", "/connect"):
            ssid = (payload.get("ssid") or "").strip()
            if not ssid:
                self._json(400, {"error": "ssid fehlt"})
                return
            threading.Thread(
                target=connect_worker, args=(ssid, payload.get("psk") or ""), daemon=True
            ).start()
            self._json(200, {"accepted": True})
        else:
            self._json(404, {"error": "unbekannt"})


def serve(port):
    while True:
        try:
            ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
        except OSError:
            time.sleep(5)


def main():
    set_state(phase="idle", message="")
    threading.Thread(target=hotspot_reaper, daemon=True).start()
    threading.Thread(target=serve, args=(PORTAL_PORT,), daemon=True).start()
    serve(API_PORT)


if __name__ == "__main__":
    main()
