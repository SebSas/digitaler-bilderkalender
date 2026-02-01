# Architektur – C4 Level 3 (Components) – DBK

## Überblick

Der **Digitale Bilderkalender (DBK)** ist als Client/Server-System aufgebaut:

- **Server** ist der `framework-server` mit **Immich** als Quelle der Bilder.
- **Client** ist ein **Raspberry Pi** mit Display, der Bilder **lokal spiegelt** (Snapshot) und sie über eine **Kiosk-Webapp** anzeigt.
- Die Verbindung zwischen Client und Server erfolgt über **Tailscale** (VPN/MagicDNS).

Wichtiges Prinzip:  
**Quelle der Wahrheit ist das Immich-Album.**  
Der DBK-Client arbeitet mit einem **lokalen Snapshot** (lokales Dateisystem), um Anzeige und Performance stabil zu halten.

---

## Component Diagram (DBK – Top Down)

```mermaid
flowchart TB
  subgraph DBK[DBK Client (Raspberry Pi)]
    subgraph WEB[Web UI (Chromium)]
      UI[Slideshow UI\n(fullscreen + touch)]
      FOOTER[Footer UI\n(time/date/holiday/weather)]
      CFG[Client Config Loader\n(location/settings)]
      UI --> FOOTER
      UI --> CFG
    end

    subgraph WEB_SRV[dbk-web (Nginx)]
      STATIC[Static Assets\n(index.html, js, css)]
      RP[Reverse Proxy\nsame-origin /api -> dbk-api]
      STATIC --> RP
    end

    subgraph API[dbk-api]
      IMG_IDX[Image Index Endpoint\nGET /api/images]
      IMG_GET[Image Content Endpoint\nGET /api/image/{id}]
      HEALTH[Health Endpoint\nGET /api/health]
      META[Optional: Metadata/Info\n(e.g. EXIF/date sorting)]
      IMG_IDX --> META
    end

    subgraph STORE[Local Storage]
      ALBUM_DIR[Album Snapshot Folder\n(downloaded photos)]
      CACHE[Cache Folder\n(derived data: weather/geocode/etc.)]
    end

    subgraph SYNC[Sync/Downloader]
      FETCH[Fetch Album Media\n(Immich/API/etc.)]
      MIRROR[Mirror to Local Folder\n(add/update/delete)]
      FETCH --> MIRROR
      MIRROR --> ALBUM_DIR
    end

    UI -->|GET same-origin| WEB_SRV
    WEB_SRV -->|/api/*| API
    IMG_IDX --> ALBUM_DIR
    IMG_GET --> ALBUM_DIR
    FOOTER -.->|optional cached data| CACHE
    API --> CACHE
  end
```

---

## Komponenten im Detail

### 1) Web UI (Chromium Kiosk)

**Zweck**  
- Stellt die Benutzeroberfläche dar: Vollbild-Slideshow, Touch-Interaktion, ggf. Footer.
- Ist absichtlich „dumm“ gehalten: holt Daten über HTTP, rendert, reagiert auf Touch.

**Eingaben**
- `GET /api/images` (Liste verfügbarer Bilder / IDs)
- `GET /api/image/{id}` (Bilddaten)
- ggf. `location.json` bzw. UI-Konfiguration (Ort/Zeitzone/Anzeigeoptionen)
- ggf. optionale Endpoints für Footer (Wetter/Feiertage)

**Ausgaben**
- Darstellung der Bilder auf dem Display im Kioskmodus

**Wichtige Designentscheidungen**
- **same-origin API**: Die UI ruft `"/api/..."` auf (kein harter Hostname), damit:
  - Reverse Proxy sauber funktioniert
  - CORS-Probleme vermieden werden
  - Betrieb offline/isoliert einfacher ist

**Failure Modes / typische Fehlerbilder**
- Schwarzer Bildschirm → meist `fetch`/JS Fehler, leere Liste, falsches Routing `/api`, nicht erreichbarer Proxy
- Bilder laden nicht → 404/500 bei `/api/image/{id}`, falscher Pfad im Backend, Storage nicht gemountet
- UI zeigt alte Version → Browsercache / Static Assets nicht aktualisiert / falsches `web-dist` im Container

**Tests als Doku (Empfehlung)**
- *UI ist schwer unit-testbar ohne Browserautomation.*  
  Minimal sinnvoll:
  - `test_config_load_defaults_when_missing()` (JS Unit)
  - `test_image_list_empty_shows_fallback()` (JS Unit / snapshot)
  - Optional später: Playwright Smoke-Test “loads first image within X seconds”

---

### 2) dbk-web (Nginx: Static + Reverse Proxy)

**Zweck**
- Liefert statische Assets aus (`index.html`, JS, CSS).
- Terminiert die Requests der UI und leitet `"/api/*"` an `dbk-api` weiter.

**Eingaben**
- HTTP Requests vom Chromium (localhost)
- Konfiguration (Nginx conf), Docker Networking (Service Discovery)

**Ausgaben**
- Static files
- Proxied API Responses

**Wichtige Designentscheidungen**
- Reverse Proxy so, dass UI **keine direkten Hostnamen** kennt:
  - `fetch("/api/images")` funktioniert immer innerhalb des lokalen Kontextes

**Failure Modes**
- `/api/*` geht nicht → Nginx Proxy falsch konfiguriert oder `dbk-api` nicht erreichbar im Docker-Netz
- Static wird nicht aktualisiert → falsches volume, falsches Build, Container nicht neu gestartet

**Tests als Doku (Empfehlung)**
- Eher Integration:
  - `curl http://127.0.0.1:8080 | head` enthält erwartete HTML Marker
  - `curl http://127.0.0.1:8080/api/health` liefert OK

---

### 3) dbk-api (HTTP API)

**Zweck**
- Liefert der UI eine Liste der verfügbaren Bilder (Index).
- Liefert Bilddaten per ID.
- Optional: zusätzliche Meta- und Cache-Endpunkte (Wetter/Geocode/Feiertage).

**Kern-Endpunkte**
- `GET /api/health`
  - schnelle Verfügbarkeit / Konfig-Check (z. B. Album dir)
- `GET /api/images`
  - liefert Liste von Bildern/IDs
- `GET /api/image/{id}`
  - liefert Bildbytes (und passenden Content-Type)

**Eingaben**
- Lokales Album-Verzeichnis (Snapshot) z. B. `/album` gemountet in Container
- Optional Cache-Verzeichnis (derived data)

**Ausgaben**
- JSON (Index, Health, optional Meta)
- Bildbytes (jpeg/png/webp/… je nach Quelle bzw. nach Konvertierung)

**Wichtige Designentscheidungen**
- Der DBK zeigt **lokale Dateien**, nicht direkt aus Immich streamen.
  - Vorteil: stabil, schnell, unabhängig von Server-Latenz
- API kapselt Dateisystemzugriffe:
  - UI muss keine Pfade kennen

**Failure Modes**
- `/api/images` liefert leer → Sync hat nichts gespiegelt, falsches Album-Verzeichnis, Mount fehlt
- `/api/image/{id}` 404 → ID-Mapping falsch (z. B. Dateiname vs. Hash)
- 500 beim Laden → Formatproblem (HEIC, kaputte Datei), Berechtigungen, fehlende Libraries

**Tests als Doku (sehr empfehlenswert)**
- `test_health_returns_ok_and_album_dir()`
- `test_images_returns_sorted_list()`
- `test_images_filters_only_supported_extensions()`
- `test_image_id_returns_bytes_and_content_type()`
- `test_image_id_unknown_returns_404()`
- `test_images_ignores_hidden_files_and_temp_files()`

> Die Tests sind hier wirklich “Living Documentation”: Sie definieren den Vertrag zwischen UI und API.

---

### 4) Local Storage (Album Snapshot)

**Zweck**
- Persistenter lokaler Speicher der Fotos, die DBK anzeigen soll.
- Ermöglicht schnelle Anzeige ohne Netzwerk- oder Immich-Abhängigkeit in Echtzeit.

**Eingaben**
- Sync/Downloader Job schreibt/aktualisiert Dateien im Snapshot-Ordner.

**Ausgaben**
- Dateien, die `dbk-api` indexiert und ausliefert.

**Wichtige Designentscheidungen**
- „Snapshot“-Charakter: Der Stand ist **eventuell konsistent** (z. B. alle X Minuten).
- Layout/Ordnerstruktur sollte stabil bleiben (damit IDs/Links konsistent sind).

**Failure Modes**
- Mount fehlt → DBK zeigt nichts
- Rechte falsch → API kann nicht lesen
- Storage voll → Sync bricht ab oder schreibt unvollständig

**Tests/Checks als Doku**
- Shell Checks:
  - `findmnt /mnt/picstorage`
  - `ls -la <album_dir> | head`
  - `df -h`
- API Tests decken indirekt Storage-Probleme auf (leere Liste etc.)

---

### 5) Sync/Downloader Job (Album → Snapshot)

**Zweck**
- Überführt das Immich-Album (Quelle der Wahrheit) in eine lokale, anzeigbare Dateimenge.
- Synchronisiert Änderungen:
  - neue Bilder hinzufügen
  - entfernte Bilder löschen
  - ggf. Metadaten/Sortierung berücksichtigen

**Eingaben**
- Immich Album Inhalt (konkret: über API, Export, o. ä.)
- Authentifizierung/Token für den dedizierten Benutzer

**Ausgaben**
- aktualisiertes lokales Snapshot-Verzeichnis

**Wichtige Designentscheidungen**
- Job läuft **periodisch** (Cron oder systemd timer) oder on-demand.
- Job muss **idempotent** sein: mehrfach laufen ohne Nebenwirkungen.
- Job sollte **gegen Parallelität geschützt** sein (`flock`/Lockfile), damit zwei Läufe nicht kollidieren.

**Failure Modes**
- Auth bricht → Download stoppt, Snapshot bleibt alt
- Netzwerk/Tailscale down → Snapshot bleibt alt (UI läuft weiter)
- Teilweise Syncs → inkonsistente Ordner (deshalb: atomare Writes/Tempfiles sinnvoll)

**Tests als Doku (sehr empfehlenswert)**
- `test_mirror_adds_new_files()`
- `test_mirror_deletes_removed_files()`
- `test_mirror_is_idempotent()`
- `test_locking_prevents_parallel_runs()`
- `test_temp_files_not_exposed_to_api()` (wichtig, falls du per temp file schreibst)

---

## Datenfluss – End-to-End (verständlich, aber präzise)

1. Auf iOS werden Fotos erstellt und in Immich hochgeladen.  
2. Ein dedizierter Immich-User („Digi Bilderkalender Ana“) hat Zugriff auf das geteilte Album („Digi Kalender Ana“).  
3. Der DBK-Client erreicht den `framework-server` über Tailscale (VPN/MagicDNS).  
4. Ein Sync-Job spiegelt den Album-Inhalt in ein lokales Snapshot-Verzeichnis auf dem DBK-Client.  
5. Die Kiosk-Webapp ruft `/api/images` ab, lädt das aktuelle Bild über `/api/image/{id}` und rendert es im Fullscreen.

---

## Abgrenzungen / bewusst nicht (Level 3)

- Wie genau der Sync technisch umgesetzt ist (Immich API vs Export vs rsync) → folgt später.
- UI-Design-Details (Transitions, Ken Burns, Footer Inhalte) → separates UI-Kapitel.
- Deployment/Build-Prozess (docker build/pull, volumes, compose) → separates Ops-Kapitel.

---

## Warum diese Struktur sinnvoll ist

- **Stabilität:** UI ist unabhängig von momentaner Server-Latenz, weil lokal gecached.  
- **Debugbarkeit:** Klare Schnittstellen (HTTP + Filesystem).  
- **Erweiterbarkeit:** Mehr Kalender = weiterer Sync + weiterer Album-Ordner + ggf. weitere Konfig.
