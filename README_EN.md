# Digital Picture Calendar (DBK)

A kiosk-based digital picture calendar on a Raspberry Pi 4 with a Waveshare touch display.
The Pi automatically starts a fullscreen web view (Chromium kiosk). The frontend is static
(Nginx), the backend (FastAPI) serves the image list, renders images as WebP (incl. cache)
and provides additional data (system telemetry, weather, holidays, geocoding).

> **Documentation concept:** This README describes concept, design, installation and
> operation. Project status, open issues and tasks are **not** maintained here but in the
> personal knowledge base.

Architecture docs: [doc/dbk_c4_level3_components.md](doc/dbk_c4_level3_components.md)

---

## Concept

- **Source of truth** is a shared Immich album on the home server (dedicated Immich user).
  Photos are added to the album from iOS devices.
- The DBK client (this Pi) **mirrors the album as a local snapshot** and displays it —
  the display stays stable, fast and independent of network/server availability.
- Client ↔ server connectivity via **Tailscale** (VPN/MagicDNS).
- Touch-only operation: fullscreen slideshow, footer with clock/date/weather, debug overlay
  via **tapping 5× in the top-left corner**, sync and shutdown functions in the GUI.
- Designed for **24/7 operation**: as little energy consumption as possible while keeping
  a modern UI.

---

## Hardware

- Raspberry Pi 4
- Display: Waveshare 10.1EP-CAPLCD (touch, 1920×1200)
  Wiki: https://www.waveshare.com/wiki/10.1EP-CAPLCD
- Active cooling (design): Noctua 4-pin PWM fan (PWM: BCM18, enable/power gate: BCM17)
- 3D-printed case / mount
- Storage mount:
  - `/mnt/picstorage` (automount)
  - Album folder: `/mnt/picstorage/picstorage-album/Digi Bilderkalender Ana/`
  - Images include `.HEIC` (backend converts to WebP)

---

## OS / System

- Raspberry Pi OS 64-bit (Trixie Lite)
- Graphics: Xorg + Openbox
- Browser: Chromium in kiosk mode
- Note: display detection can be flaky after a cold start (hence the robust HDMI config +
  kiosk health check)

---

## Display / HDMI Configuration

Relevant entries in `/boot/firmware/config.txt`:

```ini
dtoverlay=vc4-kms-v3d
max_framebuffers=2

hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt=1920 1200 60 6 0 0 0

config_hdmi_boost=7
```

Kernel check whether HDMI is connected:

```bash
for f in /sys/class/drm/*HDMI*/status; do echo "$f: $(cat "$f")"; done
```

---

## Architecture

Client/server system (diagrams: `doc/dbk_c4_level3_components.md`):

### Components
- **dbk-web** (Nginx)
  - static frontend from `dbk-web/web-dist/`
  - reverse proxy: `/api/*` → `http://dbk-api:8090/api/*` (same-origin for the UI, no CORS)
- **dbk-api** (FastAPI + Uvicorn)
  - Images: `/api/images`, `/api/image/{id}`, `/api/thumb/{id}`
  - System: `/api/health`, `/api/system`
  - Footer data: `/api/weather`, `/api/holidays`, `/api/geocode`
  - Admin: `/api/admin/immich-sync` (GET/POST), `/api/admin/shutdown` (GET/POST)
  - Reads the album under `/album`, renders/caches WebP under `/cache`
    (max 1920×1200, thumbs max 512 px)
  - **Image queues:** returns a queue label per image (`short` < 30 days in the album,
    `mid` 30–210 days, `long` > 210 days) based on `first_seen.json` in the cache;
    the UI shows new images frequently, midterm every ~10 min, longterm ~1×/h
    (scheduler in `app/slideshow.js`; dwell 90 s)

### Ports
- Web (Nginx): `http://127.0.0.1:8080`
- API (Uvicorn): `http://127.0.0.1:8090`
- Health via web (reverse proxied): `http://127.0.0.1:8080/api/health`

---

## Repo Structure (mono-repo)

```
digitaler-bilderkalender/
├─ README.md
├─ .gitignore
├─ doc/
│  ├─ dbk_c4_level3_components.md   # architecture (C4 level 3)
│  └─ fan-tests/                    # PWM matrix test reports (JSON)
├─ dbk-web/
│  ├─ docker-compose.yml
│  ├─ nginx.conf
│  └─ web-dist/                     # static frontend (deployment artifact)
├─ dbk-api/
│  ├─ docker-compose.yml
│  ├─ Dockerfile
│  ├─ app/main.py                   # FastAPI entry
│  └─ cache/                        # generated (ignored by git)
├─ immichdl/                        # album sync (backup of ~/immichdl, WITHOUT .env!)
│  ├─ sync_album.sh                 # orchestration: download → mirror → prune → warm
│  ├─ immich_album_sync.py          # own Immich v3 downloader (stdlib only)
│  ├─ prune_cache.py                # cache cleanup for removed images
│  └─ .env.example                  # variable names (real .env stays on the Pi only)
├─ systemd/                         # backup of the units from /etc/systemd/system
├─ kiosk/openbox-autostart          # backup of ~/.config/openbox/autostart
└─ scripts/                         # operational/helper scripts (see working model)
```

**Important:** `dbk-api/cache/` is generated and **not** versioned.
`immichdl/.env` (contains the Immich API key) is excluded via `.gitignore`.

---

## Working Model: Production System vs. Git Backup

**The system itself is production** — development and operation happen directly in
`~/docker/` (containers) and `~/scripts/` (operational scripts). **This repo is backup/
versioning only**; nothing is deployed or started from the repo.

| Production (source) | Backup in repo | Sync direction: production → repo |
| --- | --- | --- |
| `~/docker/dbk-api/`, `~/docker/dbk-web/` | `dbk-api/`, `dbk-web/` | `scripts/sync_docker_to_git.sh` (rsync, `DRY_RUN=1` supported) |
| `~/scripts/` | `scripts/` | copy **manually** (not covered by the sync script!) |
| `~/immichdl/` (without `.env`) | `immichdl/` | copy **manually** |
| `/etc/systemd/system/dbk-*` | `systemd/` | copy **manually** |
| `~/.config/openbox/autostart` | `kiosk/openbox-autostart` | copy **manually** |

> After changing the production system, remember to sync the changes into the repo and commit.

---

## Album Sync (Immich)

Triggered via the sync button in the GUI or `POST /api/admin/immich-sync`; flow in
`~/immichdl/sync_album.sh` (log: `~/docker/dbk-api/cache/immich_sync.log`):

1. **Download** the album via `immich_album_sync.py` — own Immich-v3-compatible downloader
   (stdlib only; `POST /api/search/metadata` + `GET /api/assets/{id}/original`). Access via
   `~/immichdl/.env` (`IMMICH_BASE_URL`, `IMMICH_API_KEY` of the dedicated user).
2. **Guard:** if the download is empty or incomplete, the script aborts **before** touching
   the local snapshot (no wipe on album-name mismatches etc.).
3. **Mirror** into the album folder (hard replace — images removed in Immich disappear
   locally as well), then **prune** their cache files.
4. **Cache pre-warming:** every image is converted once to WebP (full + thumb) so that
   display/swiping never triggers conversion storms.
5. `sync` flush so a later storage dropout cannot roll back the result.

> The Immich album name (`IMMICH_ALBUM`) is configured separately from the local folder
> name — the folder name is baked into the compose mount and stays stable.

---

## systemd Services

| Service | Purpose |
| --- | --- |
| `dbk-stack.service` | starts the Docker stack (`~/docker/dbk-api` + `~/docker/dbk-web`), deterministically triggers the picstorage automount first |
| `dbk-fan.service` | fan control: `temperature_control_app.py --poll-seconds 30`, requires `pigpiod.service`; clean stop via `fan_off.py` |
| `dbk-postboot-check.service` | post-boot sanity check (backend + display), runs with `DISPLAY=:0` |
| `dbk-stack-recover.timer` | self-healing: checks every minute whether the stack is down and `/mnt/picstorage` is reachable again — then restarts `dbk-stack` automatically (e.g. after USB dropouts) |

```bash
systemctl status dbk-stack dbk-fan dbk-postboot-check dbk-stack-recover.timer
journalctl -u dbk-stack-recover --since -1d
```

---

## Fan Control (design)

Core: `scripts/pwm_fan_control.py`, app: `temperature_control_app.py` (production: `~/scripts/`).

**Noctua requirements (white paper):** target PWM frequency 25 kHz (21–28 kHz allowed),
**non-inverted** signal, 100% duty = max speed. The fan's PWM input is internally pulled up
to 3.3/5 V; **open-collector drivers are not recommended** (distorted signals → erratic
behavior) — the driver stage must be CMOS/push-pull style.
Tacho: open collector, 2 pulses per revolution → `RPM = f × 60 / 2`.

**Software design:**
- Hardware PWM via pigpio on BCM18 at 25 kHz, fallback: software PWM (RPi.GPIO, 1 kHz)
- Enable signal inverted (power gate on BCM17)
- Hysteresis: ON at 60 °C, OFF below 52 °C — with confirmation samples (2× ON / 3× OFF)
- Anti-chatter: min. 300 s on / 120 s off, start boost 70% for 1.2 s, minimum running duty 50%
- Duty curve: < 75 °C → 50%, < 82 °C → 70%, else 100%
- Status export to `~/docker/dbk-api/cache/fan_status.json` → GUI debug overlay
  (shows the software state, not necessarily a physically spinning fan)
- Warns when `snd_bcm2835` is active (conflicts with hardware PWM on BCM18 → `dtparam=audio=off`)

**Test tools:** `fan_pwm_matrix_test.py` (interactive test matrix across inversion/duty
combinations, reports in `doc/fan-tests/`), `watch_gpio17.py` (observe the enable pin),
`fan_off.py` (deterministic fan off).

---

## Docker Setup

Runs from `~/docker/` (not from the repo):

```bash
# Normal operation: via systemd
sudo systemctl restart dbk-stack

# Manual (per service)
cd ~/docker/dbk-api && docker compose up -d --build
cd ~/docker/dbk-web && docker compose up -d

# Logs / health
docker logs --tail=200 dbk-api
curl -s http://127.0.0.1:8080/api/health; echo
```

Both services join the external Docker network `dbk-net`:

```bash
docker network create dbk-net   # if it does not exist yet
```

Relevant mounts (dbk-api): album read-only, `./cache:/cache`, `/sys` + `/proc` read-only
(for telemetry), `~/immichdl` (sync), Docker socket (admin functions).

---

## Nginx Reverse Proxy

`dbk-web/nginx.conf`: static root + `location /api/` → `proxy_pass http://dbk-api:8090/api/;`
(same-origin, no CORS needed).

---

## Kiosk Mode (Openbox + Chromium)

Autostart file: `~/.config/openbox/autostart`

- Hide mouse cursor (`unclutter`)
- Robustly disable DPMS/blanking multiple times (`xset`)
- Start Chromium in kiosk mode (dedicated profile `~/.config/chromium-kiosk`,
  translate/updates/sync disabled)
- Health check loop: `GET /api/health` every 15 s — on failure kill Chromium and restart

Logs:
```bash
tail -n 200 /tmp/dbk-kiosk.log
tail -n 200 /tmp/dbk-xset.log
```

Helper scripts: `reset_chromium_kiosk.sh` (kiosk restart), `screenshot.sh` (screenshot of the
running display into `~/temp/`), `dbk_reset.sh`, `update_safe.sh`.

---

## Typical Boot Problems & Troubleshooting

### Symptom: black display after cold start / power cycling

1) **Kernel detects the display?**
```bash
for f in /sys/class/drm/*HDMI*/status; do echo "$f: $(cat "$f")"; done
```

2) **Stack reachable?**
```bash
curl -s http://127.0.0.1:8080/api/health; echo
```

3) **Xorg/Openbox/Chromium running?**
```bash
ps -ef | egrep -i "Xorg|openbox|chromium" | grep -v grep
```

4) **Docker containers ok?**
```bash
docker ps
docker logs --tail=200 dbk-web
docker logs --tail=200 dbk-api
```

Additionally: `dbk_postboot_check.sh` runs automatically after boot
(`dbk-postboot-check.service`).

**Quick software-vs-panel diagnosis:** `~/scripts/screenshot.sh` grabs the X framebuffer.
If the screenshot shows the slideshow, the software renders fine and **the panel** lost its
signal lock (display quirk) → a **DPMS cycle** wakes it without restarting anything:

```bash
export DISPLAY=:0 XAUTHORITY=~/.Xauthority
xset dpms force off; sleep 3; xset dpms force on; xset s off; xset -dpms
```

If the screenshot is black instead, the software stack is the problem (checklist above).

### Symptom: stack down after a storage dropout
systemd stops `dbk-stack` when `/mnt/picstorage` goes away (`RequiresMountsFor`). The
self-healing `dbk-stack-recover.timer` restarts it automatically once the mount is
reachable again (max ~1 min delay).
Reminder: the album storage (USB card reader) belongs on a **USB2 port** — the Pi 4's
USB3 controller (VL805) showed reproducible link drops under I/O load.

### Symptom: Docker does not start after a kernel update
Newer Pi kernels (6.18+) no longer ship the legacy `ip_tables` module. If iptables is set
to "legacy", Docker fails with `Module ip_tables not found`:

```bash
sudo update-alternatives --set iptables /usr/sbin/iptables-nft
sudo update-alternatives --set ip6tables /usr/sbin/ip6tables-nft
sudo systemctl restart docker && sudo systemctl restart dbk-stack
```

### Symptom: 502 on `/api/*`
`dbk-web` is running but upstream `dbk-api` was briefly unreachable → check logs.
The kiosk health check covers this (Chromium restarts as soon as health is ok again).

---

## Git / GitHub

- Mono-repo: https://github.com/SebSas/digitaler-bilderkalender
- `.gitignore` contains `dbk-api/cache/`
- Mirror the Docker directories into the repo via `sync_docker_to_git.sh`;
  sync **scripts manually**
