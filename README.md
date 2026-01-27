# Digitaler Bilderkalender (DBK)

Ein kiosk-basierter digitaler Bilderkalender auf einem Raspberry Pi 4 mit Waveshare Touch-Display.
Der Pi startet automatisch eine Vollbild-Webansicht (Chromium Kiosk). Das Frontend ist statisch (Nginx),
das Backend (FastAPI) liefert die Bildliste und rendert Bilder als WebP (inkl. Cache).

---

## Status / Ziele

**Ist-Stand**
- Kiosk läuft: Bilder wechseln automatisch (derzeit 3 Bilder)
- `dbk-web` reverse-proxied `/api/*` auf `dbk-api`
- Healthcheck + Auto-Restart im Openbox Autostart verbessert Stabilität nach Kaltstart/Steckerziehen

**Ziel**
- Modularer Web-Code (erweiterbare GUI)
- Saubere Repo-Struktur (Mono-Repo), gut dokumentiert
- GitHub als Backup/Versionierung

---

## Hardware

- Raspberry Pi 4
- Display: Waveshare 10.1EP-CAPLCD (Touch, 1920×1200)
  Wiki: https://www.waveshare.com/wiki/10.1EP-CAPLCD
- Storage-Mount:
  - `/mnt/picstorage`
  - Album-Ordner: `/mnt/picstorage/picstorage-album/Digi Bilderkalender Ana/`
  - Bilder aktuell: `.HEIC` (Backend muss damit umgehen / konvertieren)

---

## OS / System

- Raspberry Pi OS 64-bit (Trixie Lite)
- Grafik: Xorg + Openbox
- Browser: Chromium im Kiosk-Modus
- Hinweis: Display-Erkennung kann nach Kaltstart manchmal zicken (daher robuste HDMI-Config + Kiosk-Healthcheck)

---

## Display / HDMI Konfiguration

Aktuelle relevante Einträge in `/boot/firmware/config.txt`:

```ini
dtoverlay=vc4-kms-v3d
max_framebuffers=2

hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt=1920 1200 60 6 0 0 0

config_hdmi_boost=7
```

Kernel-Check ob HDMI connected:

```bash
for f in /sys/class/drm/*HDMI*/status; do echo "$f: $(cat "$f")"; done
```

Beispiel-Ausgabe (ok):

```
/sys/class/drm/card1-HDMI-A-1/status: connected
```

---

## Architektur

### Komponenten
- **dbk-web** (Nginx)
  - statisches Frontend aus `dbk-web/web-dist/`
  - Reverse Proxy: `/api/*` → `http://dbk-api:8090/api/*`
- **dbk-api** (FastAPI + Uvicorn)
  - API Endpoints:
    - `/api/health`
    - `/api/images`
    - `/api/image/<id>`
  - Liest Album unter `/album`
  - Rendert/cached WebP unter `/cache`

### Ports
- Web (Nginx): `http://127.0.0.1:8080`
- API (Uvicorn): `http://127.0.0.1:8090`
- Health via Web (reverse proxied): `http://127.0.0.1:8080/api/health`

---

## Repo Struktur (Mono-Repo)

```
digitaler-bilderkalender/
├─ docker-compose.yml          # Root compose (orchestriert web+api)
├─ README.md
├─ .gitignore
├─ dbk-web/
│  ├─ docker-compose.yml       # historisch / ggf. später entfernen
│  ├─ nginx.conf               # Nginx server block
│  └─ web-dist/
│     └─ index.html            # statisches Frontend
├─ dbk-api/
│  ├─ docker-compose.yml       # historisch / ggf. später entfernen
│  ├─ Dockerfile
│  ├─ app/
│  │  └─ main.py               # FastAPI entry
│  └─ cache/                   # generated (ignored by git)
└─ scripts/                    # optional helper scripts
```

**Wichtig**
- `dbk-api/cache/` ist generiert und wird **nicht** in Git versioniert.

---

## Docker Setup

### Services starten (im Repo-Root)
```bash
docker compose up -d --build
docker compose ps
```

### Services stoppen
```bash
docker compose down
```

### Logs
```bash
docker compose logs -f --tail=200
```

### Healthcheck
```bash
curl -s http://127.0.0.1:8080/api/health; echo
```

---

## Root docker-compose.yml

Der Root-Compose orchestriert beide Services. Relevante Mounts:

- Album (read-only):
  `/mnt/picstorage/picstorage-album/Digi Bilderkalender Ana:/album:ro`
- Cache (read-write, lokal im Repo):
  `./dbk-api/cache:/cache`
- System Infos (read-only):
  - `/sys:/sys:ro`
  - `/proc:/proc:ro`

Netzwerk:
- externes Docker network `dbk-net` (muss existieren)

> Hinweis: Wenn `dbk-net` noch nicht existiert:
> ```bash
> docker network create dbk-net
> ```

---

## Nginx Reverse Proxy

Aktuelle `dbk-web/nginx.conf`:

```nginx
server {
  listen 80;

  location / {
    root   /usr/share/nginx/html;
    index  index.html;
    try_files $uri $uri/ /index.html;
  }

  location /api/ {
    proxy_pass http://dbk-api:8090/api/;
    proxy_http_version 1.1;

    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

---

## Kiosk Mode (Openbox + Chromium)

Autostart Datei:
- `~/.config/openbox/autostart`

### Ziel
- Mauszeiger verstecken
- DPMS/Blanking deaktivieren (robust, mehrfach)
- Chromium im Kiosk starten
- Healthcheck: Wenn der Stack nicht erreichbar → Chromium killen → neu starten

### Aktueller Autostart (robust + Healthcheck)
```bash
# Hide mouse cursor quickly
unclutter -idle 0.1 -root &

# Disable screen blanking / power management (robust)
(
  for i in 1 2 3 4 5; do
    xset s off
    xset -dpms
    xset s noblank
    sleep 1
  done
) >/tmp/dbk-xset.log 2>&1 &

# Kiosk (auto-restart + health-check)
(
  while true; do
    chromium --kiosk --noerrdialogs --disable-infobars       --check-for-update-interval=31536000       http://127.0.0.1:8080 &
    CHR_PID=$!

    # every 15s: if health fails -> restart chromium
    while kill -0 "$CHR_PID" 2>/dev/null; do
      if ! curl -fsS http://127.0.0.1:8080/api/health >/dev/null; then
        kill "$CHR_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$CHR_PID" 2>/dev/null || true
        break
      fi
      sleep 15
    done

    wait "$CHR_PID" 2>/dev/null || true
    sleep 2
  done
) >/tmp/dbk-kiosk.log 2>&1 &
```

Logs:
```bash
tail -n 200 /tmp/dbk-kiosk.log
tail -n 200 /tmp/dbk-xset.log
```

---

## Typische Boot-Probleme & Troubleshooting

### Symptom: Display schwarz nach Kaltstart / Steckerziehen
Checkliste:

1) **Kernel erkennt Display?**
```bash
for f in /sys/class/drm/*HDMI*/status; do echo "$f: $(cat "$f")"; done
```

2) **Stack erreichbar?**
```bash
curl -s http://127.0.0.1:8080/api/health; echo
```

3) **Laufen Xorg/Openbox/Chromium?**
```bash
ps -ef | egrep -i "Xorg|openbox|chromium" | grep -v grep
```

4) **Docker Container ok?**
```bash
docker ps
docker logs --tail=200 dbk-web
docker logs --tail=200 dbk-api
```

### Symptom: 502 bei `/api/*`
Das heißt: `dbk-web` läuft, aber Upstream `dbk-api` war kurz nicht da oder nicht erreichbar.
- `dbk-api` Logs checken
- `docker ps` checken
- Kiosk-Healthcheck fängt das ab (Chromium wird neu gestartet sobald Health wieder sauber ist)

---

## Development Workflow (Content / Modularisierung)

### Frontend
- aktuell: `dbk-web/web-dist/index.html` (statisch)
- Modularisierungsidee:
  - später `dbk-web/src/` (React o.ä.) + Build nach `web-dist/`
  - `web-dist/` bleibt das Deployment-Artifact für Nginx

### Backend
- `dbk-api/app/main.py`
- zukünftige sinnvolle Struktur:
  - `app/routers/`
  - `app/services/` (Image discovery, HEIC decode, cache, etc.)
  - `app/config.py` (env handling)

### Cache
- `dbk-api/cache/` ist **generated**
- kann jederzeit gelöscht werden:
```bash
rm -rf dbk-api/cache/*
```

---

## Git / GitHub

- Mono-Repo ist bereits initialisiert und pushed.
- `.gitignore` enthält `dbk-api/cache/` (Cache bleibt lokal).
- Empfohlen: eigener SSH-Key pro Gerät (Pi), um Keys getrennt widerrufen zu können.

---

## Roadmap (grobe Idee)

- [ ] Frontend modularisieren (React, Komponenten, sauberes State-Handling)
- [ ] UI: Album-Auswahl / Zeitsteuerung / Übergänge / Debug-Overlay
- [ ] Backend: robustes HEIC Handling + Preload/Cache management
- [ ] Health / Watchdog: optional systemd service für Kiosk/Stack
- [ ] Branding: eigener Boot-Splash (Plymouth Theme)

---
