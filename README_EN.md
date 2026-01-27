# Digital Picture Calendar (DBK)

A kiosk-based digital picture calendar on a Raspberry Pi 4 with a Waveshare touch display.
The Pi automatically starts a fullscreen web view (Chromium Kiosk). The frontend is static (Nginx),
the backend (FastAPI) provides the image list and renders images as WebP (including cache).

---

## Status / Goals

**Current state**
- Kiosk runs: images change automatically (currently 3 images)
- `dbk-web` reverse-proxied `/api/*` to `dbk-api`
- Healthcheck + auto-restart in the Openbox autostart improved stability after cold boot / unplugging

**Goal**
- Modular web code (extensible GUI)
- Clean repo structure (monorepo), well documented
- GitHub as backup/versioning

---

## Hardware

- Raspberry Pi 4
- Display: Waveshare 10.1EP-CAPLCD (Touch, 1920×1200)
  Wiki: https://www.waveshare.com/wiki/10.1EP-CAPLCD
- Storage mount:
  - `/mnt/picstorage`
  - Album folder: `/mnt/picstorage/picstorage-album/Digi Bilderkalender Ana/`
  - Images currently: `.HEIC` (backend must handle/convert these)

---

## OS / System

- Raspberry Pi OS 64-bit (Trixie Lite)
- Graphics: Xorg + Openbox
- Browser: Chromium in Kiosk mode
- Note: Display detection can sometimes be flaky after cold boot (so use a robust HDMI config + kiosk healthcheck)

---

## Display / HDMI Configuration

Current relevant entries in `/boot/firmware/config.txt`:

```ini
dtoverlay=vc4-kms-v3d
max_framebuffers=2

hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt=1920 1200 60 6 0 0 0

config_hdmi_boost=7
```

Check kernel for HDMI connected:

```bash
for f in /sys/class/drm/*HDMI*/status; do echo "$f: $(cat "$f")"; done
```

Example output (ok):

```
/sys/class/drm/card1-HDMI-A-1/status: connected
```

---

## Architecture

### Components
- **dbk-web** (Nginx)
  - static frontend from `dbk-web/web-dist/`
  - Reverse proxy: `/api/*` → `http://dbk-api:8090/api/*`
- **dbk-api** (FastAPI + Uvicorn)
  - API endpoints:
    - `/api/health`
    - `/api/images`
    - `/api/image/<id>`
  - Reads album under `/album`
  - Renders/caches WebP under `/cache`

### Ports
- Web (Nginx): `http://127.0.0.1:8080`
- API (Uvicorn): `http://127.0.0.1:8090`
- Health via Web (reverse proxied): `http://127.0.0.1:8080/api/health`

---

## Repo Structure (Monorepo)

```
digitaler-bilderkalender/
├─ docker-compose.yml          # Root compose (orchestrates web+api)
├─ README.md
├─ .gitignore
├─ dbk-web/
│  ├─ docker-compose.yml       # historical / possibly removed later
│  ├─ nginx.conf               # Nginx server block
│  └─ web-dist/
│     └─ index.html            # static frontend
├─ dbk-api/
│  ├─ docker-compose.yml       # historical / possibly removed later
│  ├─ Dockerfile
│  ├─ app/
│  │  └─ main.py               # FastAPI entry
│  └─ cache/                   # generated (ignored by git)
└─ scripts/                    # optional helper scripts
```

**Important**
- `dbk-api/cache/` is generated and is **not** versioned in Git.

---

## Docker Setup

### Start services (in repo root)
```bash
docker compose up -d --build
docker compose ps
```

### Stop services
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

The root compose orchestrates both services. Relevant mounts:

- Album (read-only):
  `/mnt/picstorage/picstorage-album/Digi Bilderkalender Ana:/album:ro`
- Cache (read-write, local in repo):
  `./dbk-api/cache:/cache`
- System info (read-only):
  - `/sys:/sys:ro`
  - `/proc:/proc:ro`

Network:
- external Docker network `dbk-net` (must exist)

> Note: If `dbk-net` does not yet exist:
> ```bash
> docker network create dbk-net
> ```

---

## Nginx Reverse Proxy

Current `dbk-web/nginx.conf`:

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

Autostart file:
- `~/.config/openbox/autostart`

### Goals
- Hide mouse cursor
- Disable DPMS / screen blanking (robust, multiple attempts)
- Start Chromium in kiosk mode
- Healthcheck: if stack is unreachable → kill Chromium → restart

### Current autostart (robust + healthcheck)
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

## Typical Boot Problems & Troubleshooting

### Symptom: Display black after cold boot / unplugging
Checklist:

1) **Does the kernel detect the display?**
```bash
for f in /sys/class/drm/*HDMI*/status; do echo "$f: $(cat "$f")"; done
```

2) **Is the stack reachable?**
```bash
curl -s http://127.0.0.1:8080/api/health; echo
```

3) **Are Xorg/Openbox/Chromium running?**
```bash
ps -ef | egrep -i "Xorg|openbox|chromium" | grep -v grep
```

4) **Are Docker containers ok?**
```bash
docker ps
docker logs --tail=200 dbk-web
docker logs --tail=200 dbk-api
```

### Symptom: 502 on `/api/*`
This means: `dbk-web` is running, but upstream `dbk-api` was briefly unavailable or unreachable.
- Check `dbk-api` logs
- Check `docker ps`
- Kiosk healthcheck handles this (Chromium will be restarted once health is good again)

---

## Development Workflow (Content / Modularization)

### Frontend
- currently: `dbk-web/web-dist/index.html` (static)
- Modularization idea:
  - later `dbk-web/src/` (React or similar) + build to `web-dist/`
  - `web-dist/` remains the deployment artifact for Nginx

### Backend
- `dbk-api/app/main.py`
- future sensible structure:
  - `app/routers/`
  - `app/services/` (image discovery, HEIC decode, cache, etc.)
  - `app/config.py` (env handling)

### Cache
- `dbk-api/cache/` is **generated**
- can be deleted at any time:
```bash
rm -rf dbk-api/cache/*
```

---

## Git / GitHub

- Monorepo is already initialized and pushed.
- `.gitignore` contains `dbk-api/cache/` (cache stays local).
- Recommended: a separate SSH key per device (Pi), so keys can be revoked individually.

---

## Roadmap (rough idea)

- [ ] Modularize frontend (React, components, clean state handling)
- [ ] UI: album selection / time control / transitions / debug overlay
- [ ] Backend: robust HEIC handling + preload/cache management
- [ ] Health / watchdog: optional systemd service for kiosk/stack
- [ ] Branding: custom boot splash (Plymouth theme)

---
