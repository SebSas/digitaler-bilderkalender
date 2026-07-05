# Digitaler Bilderkalender (DBK)

Ein kiosk-basierter digitaler Bilderkalender auf einem Raspberry Pi 4 mit Waveshare Touch-Display.
Der Pi startet automatisch eine Vollbild-Webansicht (Chromium Kiosk). Das Frontend ist statisch (Nginx),
das Backend (FastAPI) liefert die Bildliste, rendert Bilder als WebP (inkl. Cache) und stellt
Zusatzdaten bereit (System-Telemetrie, Wetter, Feiertage, Geocoding).

Architektur-Doku: [doc/dbk_c4_level3_components.md](doc/dbk_c4_level3_components.md)

---

## Status / Ziele

**Ist-Stand (2026-07)**
- System läuft produktiv und stabil (Container-Uptime mehrere Monate)
- Kiosk zeigt Diashow aus dem Immich-Album (lokaler Snapshot)
- GUI: Vollbild-Slideshow, Footer mit Uhr/Datum/Wetter, Debug-Overlay mit Systemtelemetrie
  (Temperatur, CPU, RAM, Lüfterstatus, WLAN, Tailscale), Sync- und Shutdown-Button
- Betrieb vollständig über systemd: `dbk-stack`, `dbk-fan`, `dbk-postboot-check`
- Lüftersteuerung überarbeitet (Hardware-PWM 25 kHz via pigpio, Anti-Chatter-Logik) —
  das frühere Aussetzer-Problem ist behoben (siehe Abschnitt Lüftersteuerung)

**Ziele**
- Modularer Web-Code (erweiterbare GUI, z. B. React-Build nach `web-dist/`)
- Saubere Repo-Struktur (Mono-Repo), gut dokumentiert
- GitHub als Backup/Versionierung

---

## Hardware

- Raspberry Pi 4
- Display: Waveshare 10.1EP-CAPLCD (Touch, 1920×1200)
  Wiki: https://www.waveshare.com/wiki/10.1EP-CAPLCD
- Aktive Kühlung: Noctua 4-Pin-PWM-Lüfter (PWM: BCM18, Enable: BCM17)
- Storage-Mount:
  - `/mnt/picstorage` (Automount)
  - Album-Ordner: `/mnt/picstorage/picstorage-album/Digi Bilderkalender Ana/`
  - Bilder u. a. `.HEIC` (Backend konvertiert nach WebP)

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

---

## Architektur

Client/Server-System (Details und Diagramme: `doc/dbk_c4_level3_components.md`):

- **Server:** `framework-server` mit Immich. Quelle der Wahrheit ist das geteilte Album
  („Digi Kalender Ana", dedizierter Immich-User). Anbindung über **Tailscale** (MagicDNS).
- **Client (dieser Pi):** spiegelt das Album als lokalen Snapshot und zeigt ihn über die Kiosk-Webapp.

### Komponenten
- **dbk-web** (Nginx)
  - statisches Frontend aus `dbk-web/web-dist/`
  - Reverse Proxy: `/api/*` → `http://dbk-api:8090/api/*` (same-origin für die UI)
- **dbk-api** (FastAPI + Uvicorn)
  - Bilder: `/api/images`, `/api/image/{id}`, `/api/thumb/{id}`
  - System: `/api/health`, `/api/system`
  - Footer-Daten: `/api/weather`, `/api/holidays`, `/api/geocode`
  - Admin: `/api/admin/immich-sync` (GET/POST), `/api/admin/shutdown` (GET/POST)
  - Liest Album unter `/album`, rendert/cached WebP unter `/cache`
    (max 1920×1200, Thumbs max 512 px)

### Ports
- Web (Nginx): `http://127.0.0.1:8080`
- API (Uvicorn): `http://127.0.0.1:8090`
- Health via Web (reverse proxied): `http://127.0.0.1:8080/api/health`

---

## Repo-Struktur (Mono-Repo)

```
digitaler-bilderkalender/
├─ README.md
├─ .gitignore
├─ doc/
│  ├─ dbk_c4_level3_components.md   # Architektur (C4 Level 3)
│  └─ fan-tests/                    # PWM-Matrix-Testreports (JSON)
├─ dbk-web/
│  ├─ docker-compose.yml
│  ├─ nginx.conf
│  └─ web-dist/                     # statisches Frontend (Deployment-Artifact)
├─ dbk-api/
│  ├─ docker-compose.yml
│  ├─ Dockerfile
│  ├─ app/main.py                   # FastAPI entry
│  └─ cache/                        # generated (ignored by git)
└─ scripts/                         # Betriebs-/Hilfsskripte (siehe Deployment)
```

**Wichtig**
- `dbk-api/cache/` ist generiert und wird **nicht** versioniert.
- `README_EN.md` ist derzeit veraltet (Stand Jan 2026).

---

## Deployment auf dem Pi

Das Repo ist die **versionierte Kopie** — deployt wird aus separaten Verzeichnissen:

| Deployt | Versioniert im Repo | Sync |
| --- | --- | --- |
| `~/docker/dbk-api/`, `~/docker/dbk-web/` | `dbk-api/`, `dbk-web/` | `scripts/sync_docker_to_git.sh` (rsync, `DRY_RUN=1` möglich) |
| `~/scripts/` | `scripts/` | **manuell** kopieren (wird vom Sync-Skript nicht erfasst!) |

> Nach Änderungen an deployten Skripten daran denken, sie auch ins Repo zu kopieren —
> der Drift zwischen `~/scripts/` und `scripts/` war schon einmal mehrere Monate groß.

---

## systemd-Dienste

| Dienst | Zweck |
| --- | --- |
| `dbk-stack.service` | startet den Docker-Stack (`~/docker/dbk-api` + `~/docker/dbk-web`), triggert vorher den picstorage-Automount deterministisch |
| `dbk-fan.service` | Lüftersteuerung: `temperature_control_app.py --poll-seconds 30`, benötigt `pigpiod.service`; sauberes Stoppen über `fan_off.py` |
| `dbk-postboot-check.service` | Post-Boot Sanity Check (Backend + Display), läuft mit `DISPLAY=:0` |

```bash
systemctl status dbk-stack dbk-fan dbk-postboot-check
journalctl -u dbk-fan --since -1d
```

---

## Lüftersteuerung

Kern: `scripts/pwm_fan_control.py` (deployt: `~/scripts/`), App: `temperature_control_app.py`.

- **Hardware-PWM** via pigpio auf BCM18 mit **25 kHz** (Noctua-Spezifikation), Fallback: Software-PWM (RPi.GPIO, 1 kHz)
- PWM-Signal **nicht invertiert**, Enable-Signal invertiert (Power-Gate auf BCM17)
- Hysterese: EIN ab 60 °C, AUS unter 52 °C — mit Bestätigungs-Samples (2× EIN / 3× AUS)
- **Anti-Chatter:** min. 300 s an / 120 s aus, Start-Boost 70 % für 1,2 s, Mindest-Duty 50 %
- Duty-Kurve: < 75 °C → 50 %, < 82 °C → 70 %, sonst 100 %
- Status-Export nach `~/docker/dbk-api/cache/fan_status.json` → Debug-Overlay der GUI
- Warnung bei aktivem `snd_bcm2835` (Konflikt mit Hardware-PWM auf BCM18 → `dtparam=audio=off`)
- Tacho (Noctua): Open Collector, 2 Impulse/Umdrehung → `RPM = f × 60 / 2`
- Testwerkzeuge: `fan_pwm_matrix_test.py` (Reports in `doc/fan-tests/`), `watch_gpio17.py`

**Historie:** Die ursprüngliche Ansteuerung (invertiertes Software-PWM, Open-Collector-artig)
führte zu sporadischen Lüfter-Aussetzern — deckt sich mit der Noctua-Warnung vor
Open-Collector-Designs. Gelöst durch Hardware-PWM + Anti-Chatter-Logik (Feb 2026).

---

## Docker Setup

Deployt wird aus `~/docker/` (nicht aus dem Repo):

```bash
# Regelbetrieb: über systemd
sudo systemctl restart dbk-stack

# Manuell (pro Service)
cd ~/docker/dbk-api && docker compose up -d --build
cd ~/docker/dbk-web && docker compose up -d

# Logs / Health
docker logs --tail=200 dbk-api
curl -s http://127.0.0.1:8080/api/health; echo
```

Beide Services hängen im externen Docker-Netz `dbk-net`:

```bash
docker network create dbk-net   # falls noch nicht vorhanden
```

Relevante Mounts (dbk-api): Album read-only, `./cache:/cache`, `/sys` + `/proc` read-only
(für Telemetrie), `~/immichdl` (Sync), Docker-Socket (Admin-Funktionen).

---

## Nginx Reverse Proxy

`dbk-web/nginx.conf`: statisches Root + `location /api/` → `proxy_pass http://dbk-api:8090/api/;`
(same-origin, kein CORS nötig).

---

## Kiosk Mode (Openbox + Chromium)

Autostart-Datei: `~/.config/openbox/autostart`

- Mauszeiger verstecken (`unclutter`)
- DPMS/Blanking mehrfach robust deaktivieren (`xset`)
- Chromium im Kiosk starten (eigenes Profil `~/.config/chromium-kiosk`, Translate/Updates/Sync deaktiviert)
- Healthcheck-Loop: alle 15 s `GET /api/health` — bei Fehler Chromium killen und neu starten

Logs:
```bash
tail -n 200 /tmp/dbk-kiosk.log
tail -n 200 /tmp/dbk-xset.log
```

Hilfsskripte: `reset_chromium_kiosk.sh` (Kiosk-Neustart), `screenshot.sh` (Screenshot vom laufenden
Display nach `~/temp/`), `dbk_reset.sh`, `update_safe.sh`.

---

## Typische Boot-Probleme & Troubleshooting

### Symptom: Display schwarz nach Kaltstart / Steckerziehen

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

Zusätzlich: `dbk_postboot_check.sh` läuft automatisch nach dem Boot (`dbk-postboot-check.service`).

### Symptom: 502 bei `/api/*`
`dbk-web` läuft, aber Upstream `dbk-api` war kurz nicht erreichbar → Logs prüfen.
Der Kiosk-Healthcheck fängt das ab (Chromium-Neustart sobald Health wieder sauber).

---

## Git / GitHub

- Mono-Repo: https://github.com/SebSas/digitaler-bilderkalender
- `.gitignore` enthält `dbk-api/cache/`
- Docker-Verzeichnisse per `sync_docker_to_git.sh` ins Repo spiegeln; **Skripte manuell** syncen

---

## Roadmap

- [x] UI: Footer mit Uhr/Datum/Wetter
- [x] UI: Debug-Overlay mit Systemtelemetrie
- [x] UI: Sync- und Shutdown-Funktion
- [x] Backend: HEIC-Handling + WebP-Cache
- [x] Health / Watchdog: systemd-Dienste für Stack, Lüfter und Post-Boot-Check
- [x] Lüftersteuerung: Hardware-PWM + Anti-Chatter
- [ ] Frontend modularisieren (React, Komponenten, sauberes State-Handling)
- [ ] UI: Album-Auswahl / Zeitsteuerung / Übergänge
- [ ] Branding: eigener Boot-Splash (Plymouth Theme)
- [ ] README_EN.md aktualisieren oder entfernen
