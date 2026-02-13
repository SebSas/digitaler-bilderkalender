import hashlib
import json
import os
import pillow_heif
import re
import subprocess
import time
import urllib.parse
import urllib.request

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from typing import List, Dict, Optional, Tuple

# Register HEIF/HEIC support in Pillow explicitly.
# Some environments do not auto-register on import.
pillow_heif.register_heif_opener()


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Directory that contains the photo album. Mounted read-only from the host.
ALBUM_DIR = Path(os.environ.get("DBK_ALBUM_DIR", "/album"))

# Cache directory for converted images (webp/jpg). Mounted read-write.
CACHE_DIR = Path(os.environ.get("DBK_CACHE_DIR", "/cache"))

# Output format for cached images.
# "webp" is usually the best compromise for browser display + size.
CACHE_FORMAT = os.environ.get("DBK_CACHE_FORMAT", "webp").lower()

# Max edge length for full-screen images and thumbnails.
CACHE_MAX_EDGE = int(os.environ.get("DBK_CACHE_MAX_EDGE", "1920"))
THUMB_MAX_EDGE = int(os.environ.get("DBK_THUMB_MAX_EDGE", "512"))

# File extensions we consider as images in the album folder.
SUPPORTED = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}

# German state mapping for geocoding results.
STATE_NAMES = {
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}

WEATHER_REFRESH_MIN = timedelta(minutes=30)
NETWORK_TIMEOUT_S = 8

SYNC_STATE = {
    "running": False,
    "last_started": None,
    "last_finished": None,
    "last_exit_code": None,
    "last_error": None,
}
SYNC_LOCK = threading.Lock()


def _hash_path(p: Path) -> str:
    """
    Create a stable ID based on the *full path string*.
    Note: If the folder name changes, IDs will change too.
    """
    return hashlib.sha1(str(p).encode("utf-8")).hexdigest()


def _ensure_dir(p: Path) -> None:
    """Create the parent directories if they don't exist."""
    p.mkdir(parents=True, exist_ok=True)


def _resize(img: Image.Image, max_edge: int) -> Image.Image:
    """
    Resize an image so that its longest edge becomes max_edge,
    preserving aspect ratio. If image is already small enough, no-op.
    """
    w, h = img.size
    m = max(w, h)
    if m <= max_edge:
        return img

    scale = max_edge / float(m)
    nw, nh = int(w * scale), int(h * scale)
    return img.resize((nw, nh), Image.LANCZOS)


def _cache_path(src: Path, kind: str) -> Path:
    """
    Compute target cache path for an album source file.
    kind: "full" or "thumb"
    """
    h = _hash_path(src)
    ext = "webp" if CACHE_FORMAT == "webp" else "jpg"
    return CACHE_DIR / kind / f"{h}.{ext}"


def _convert(src: Path, dst: Path, max_edge: int) -> None:
    """
    Convert album image to cached output format (WEBP/JPEG).
    - Converts to RGB (safe for web display)
    - Resizes to max_edge
    - Writes to dst (creates folders as needed)
    """
    _ensure_dir(dst.parent)

    with Image.open(src) as im:
        # Respect camera orientation stored in EXIF (e.g., portrait photos).
        im = ImageOps.exif_transpose(im)
        # Normalize to RGB for consistent output.
        im = im.convert("RGB")
        im = _resize(im, max_edge)

        if CACHE_FORMAT == "webp":
            # WEBP: good size/quality for kiosk usage.
            im.save(dst, "WEBP", quality=85, method=6)
        else:
            # JPEG fallback: widely supported.
            im.save(dst, "JPEG", quality=85, optimize=True)


def _list_images() -> List[Path]:
    """
    Recursively scan the album directory and return all supported image files,
    sorted by filename (case-insensitive).
    """
    if not ALBUM_DIR.exists():
        return []

    files: List[Path] = []
    for p in ALBUM_DIR.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            files.append(p)

    files.sort(key=lambda x: x.name.lower())
    return files


def _find_by_id(image_id: str) -> Path:
    """
    Resolve an image_id to the matching file path in the album.
    This is O(n) over the album list; fine for small/medium albums.
    If the album grows large, we can add an index/cache later.
    """
    for p in _list_images():
        if _hash_path(p) == image_id:
            return p
    raise HTTPException(status_code=404, detail="image not found")


def _run(cmd: List[str]) -> str:
    """Run a command and return stdout (stripped)."""
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return out.strip()
    except Exception as e:
        return f"ERR: {e}"
def _read_cpu_temp_c() -> Optional[float]:
    """Read CPU temp from sysfs (works if /sys is mounted into the container)."""
    p = Path("/sys/class/thermal/thermal_zone0/temp")
    if not p.exists():
        return None
    return int(p.read_text().strip()) / 1000.0


def _read_uptime_s() -> Optional[float]:
    """Read uptime from /proc (works if /proc is mounted into the container)."""
    p = Path("/proc/uptime")
    if not p.exists():
        return None
    return float(p.read_text().split()[0])


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _normalize_key(value: str) -> str:
    s = value.strip().lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def _read_json(path: Path) -> Optional[Dict[str, object]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: Dict[str, object]) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_updated_at(data: Optional[Dict[str, object]]) -> Optional[datetime]:
    if not data:
        return None
    ts = data.get("updated_at")
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _fetch_json_url(url: str, timeout_s: int = NETWORK_TIMEOUT_S) -> Dict[str, object]:
    req = urllib.request.Request(url, headers={"User-Agent": "dbk-api/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as res:
        data = res.read().decode("utf-8")
        return json.loads(data)


def _geocode_cache_path(state_norm: str, name_norm: str) -> Path:
    return CACHE_DIR / f"geocode.de-{state_norm}-{name_norm}.json"


def _weather_cache_path(state_norm: str, name_norm: str) -> Path:
    return CACHE_DIR / f"weather.de-{state_norm}-{name_norm}.json"


def _holidays_cache_path(state_norm: str, year: int) -> Path:
    return CACHE_DIR / f"holidays.de-{state_norm}-{year}.json"


def _weather_code_to_text_icon(code: int) -> Tuple[str, str]:
    if code == 0:
        return "Sonnig", "sunny"
    if code in (1, 2):
        return "Teilweise bewölkt", "partly_cloudy_day"
    if code == 3:
        return "Bewölkt", "cloudy"
    if code in (45, 48):
        return "Nebel", "fog"
    if code in (51, 53, 55):
        return "Nieselregen", "drizzle"
    if code in (61, 63, 65):
        return "Regen", "rain"
    if code in (66, 67):
        return "Eisregen", "rain"
    if code in (71, 73, 75):
        return "Schnee", "snow"
    if code == 77:
        return "Schneegriesel", "snow"
    if code in (80, 81, 82):
        return "Schauer", "rain"
    if code in (85, 86):
        return "Schneeschauer", "snow"
    if code in (95, 96, 99):
        return "Gewitter", "storm"
    return "Unbekannt", "unknown"


def _fetch_geocode(name: str, state: str) -> Dict[str, object]:
    params = {
        "name": name,
        "count": 5,
        "language": "de",
        "format": "json",
        "country": "DE",
    }
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(params)
    data = _fetch_json_url(url)
    results = data.get("results") or []
    if not isinstance(results, list) or not results:
        raise ValueError("location not found")

    state_name = STATE_NAMES.get(state.upper())
    chosen = results[0]
    if state_name:
        for item in results:
            if str(item.get("admin1", "")).lower() == state_name.lower():
                chosen = item
                break

    display_parts = [chosen.get("name"), chosen.get("admin1"), chosen.get("country")]
    display_name = ", ".join([p for p in display_parts if p])

    return {
        "status": "ok",
        "country": "DE",
        "state": state.upper(),
        "name": name,
        "lat": float(chosen["latitude"]),
        "lon": float(chosen["longitude"]),
        "timezone": chosen.get("timezone") or "Europe/Berlin",
        "resolved_display_name": display_name,
        "updated_at": _now_iso(),
    }


def _fetch_weather(geo: Dict[str, object]) -> Dict[str, object]:
    lat = geo["lat"]
    lon = geo["lon"]
    timezone_name = geo.get("timezone") or "Europe/Berlin"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone_name,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = _fetch_json_url(url)
    current = data.get("current") or {}
    daily = data.get("daily") or {}

    current_temp = int(round(float(current.get("temperature_2m", 0))))
    current_code = int(current.get("weather_code", -1))
    current_text, current_icon = _weather_code_to_text_icon(current_code)

    times = daily.get("time") or []
    maxs = daily.get("temperature_2m_max") or []
    mins = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []

    today = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    forecast = []
    for idx, date_str in enumerate(times):
        if date_str <= today:
            continue
        if idx >= len(maxs) or idx >= len(mins) or idx >= len(codes):
            continue
        text, icon = _weather_code_to_text_icon(int(codes[idx]))
        forecast.append({
            "date": date_str,
            "min_c": int(round(float(mins[idx]))),
            "max_c": int(round(float(maxs[idx]))),
            "icon": icon,
        })
        if len(forecast) >= 3:
            break

    return {
        "status": "ok",
        "updated_at": _now_iso(),
        "location": {
            "country": "DE",
            "state": geo["state"],
            "name": geo["name"],
            "lat": lat,
            "lon": lon,
            "timezone": timezone_name,
        },
        "current": {
            "temp_c": current_temp,
            "condition_text": current_text,
            "icon": current_icon,
        },
        "forecast_3d": forecast,
    }


def _fetch_holidays(state: str, year: int) -> Dict[str, object]:
    params = {
        "jahr": str(year),
        "nur_land": state.upper(),
    }
    url = "https://feiertage-api.de/api/?" + urllib.parse.urlencode(params)
    data = _fetch_json_url(url)
    days = []
    if isinstance(data, dict):
        for name, info in data.items():
            if isinstance(info, dict) and info.get("datum"):
                days.append({"date": info["datum"], "name": name})
    days.sort(key=lambda d: d["date"])
    return {
        "status": "ok",
        "updated_at": _now_iso(),
        "country": "DE",
        "state": state.upper(),
        "year": int(year),
        "days": days,
    }


def _sync_log_path() -> Path:
    return CACHE_DIR / "immich_sync.log"


def _run_immich_sync() -> None:
    try:
        script = Path("/home/sebi/immichdl/sync_album.sh")
        if not script.exists():
            SYNC_STATE["last_error"] = "sync script not found"
            return
        log_path = _sync_log_path()
        with log_path.open("a", encoding="utf-8") as logf:
            logf.write(f"\n[{_now_iso()}] sync start\n")
            logf.flush()
            proc = subprocess.Popen(
                ["/bin/bash", str(script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            if proc.stdout is not None:
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    logf.write(f"[{_now_iso()}] {line}\n")
                    logf.flush()
            exit_code = proc.wait()
            SYNC_STATE["last_exit_code"] = exit_code
            if exit_code != 0:
                SYNC_STATE["last_error"] = f"exit {exit_code}"
            logf.write(f"[{_now_iso()}] sync end (exit {exit_code})\n")
            logf.flush()
    except Exception as e:
        SYNC_STATE["last_error"] = str(e)
    finally:
        SYNC_STATE["running"] = False
        SYNC_STATE["last_finished"] = _now_iso()


@app.get("/api/system")
def system_info() -> Dict[str, object]:
    """Basic system info for the kiosk UI (temp + uptime)."""
    return {
        "temp_c": _read_cpu_temp_c(),
        "uptime_s": _read_uptime_s(),
        "ts": int(time.time()),
    }


@app.get("/api/health")
def health() -> Dict[str, object]:
    """
    Simple health endpoint used for quick checks.
    """
    return {"ok": True, "album_dir": str(ALBUM_DIR)}


@app.get("/api/images")
def images() -> JSONResponse:
    """
    Return a list of available images: [{id, name}, ...]
    """
    imgs = _list_images()
    data = [{"id": _hash_path(p), "name": p.name} for p in imgs]
    return JSONResponse(data)


@app.get("/api/image/{image_id}")
def image_full(image_id: str):
    """
    Return a full-size image (cached). Converts on demand and caches the result.
    """
    src = _find_by_id(image_id)
    dst = _cache_path(src, "full")

    # Rebuild cache if missing or if source file changed since last conversion.
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        try:
            _convert(src, dst, CACHE_MAX_EDGE)
        except UnidentifiedImageError:
            # File exists but cannot be decoded (corrupt or unsupported HEIC variant).
            raise HTTPException(status_code=422, detail=f"cannot decode image: {src.name}")

    return FileResponse(dst)


@app.get("/api/thumb/{image_id}")
def image_thumb(image_id: str):
    """
    Return a thumbnail image (cached). Converts on demand and caches the result.
    """
    src = _find_by_id(image_id)
    dst = _cache_path(src, "thumb")

    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        try:
            _convert(src, dst, THUMB_MAX_EDGE)
        except UnidentifiedImageError:
            raise HTTPException(status_code=422, detail=f"cannot decode image: {src.name}")

    return FileResponse(dst)


@app.get("/api/geocode")
def geocode(name: str, state: str, mode: str = "refresh") -> JSONResponse:
    state_norm = _normalize_key(state)
    name_norm = _normalize_key(name)
    cache_path = _geocode_cache_path(state_norm, name_norm)
    cached = _read_json(cache_path)

    if mode == "cache":
        if cached:
            return JSONResponse(cached)
        data = {
            "status": "error",
            "country": "DE",
            "state": state.upper(),
            "name": name,
            "error": "cache missing",
            "updated_at": _now_iso(),
        }
        return JSONResponse(data)

    if cached:
        return JSONResponse(cached)

    try:
        data = _fetch_geocode(name, state)
    except Exception as e:
        data = {
            "status": "error",
            "country": "DE",
            "state": state.upper(),
            "name": name,
            "error": str(e),
            "updated_at": _now_iso(),
        }
    _write_json(cache_path, data)
    return JSONResponse(data)


@app.get("/api/weather")
def weather(name: str, state: str, mode: str = "refresh") -> JSONResponse:
    state_norm = _normalize_key(state)
    name_norm = _normalize_key(name)
    cache_path = _weather_cache_path(state_norm, name_norm)
    cached = _read_json(cache_path)

    if mode == "cache":
        if cached:
            return JSONResponse(cached)
        data = {
            "status": "error",
            "error": "cache missing",
            "updated_at": _now_iso(),
        }
        return JSONResponse(data)

    last = _parse_updated_at(cached)
    if cached and cached.get("status") == "ok" and last:
        if datetime.now(last.tzinfo or timezone.utc) - last < WEATHER_REFRESH_MIN:
            return JSONResponse(cached)

    geo_cache = _read_json(_geocode_cache_path(state_norm, name_norm))
    if not geo_cache or geo_cache.get("status") != "ok":
        data = {
            "status": "error",
            "error": "geocode missing or invalid",
            "updated_at": _now_iso(),
        }
        _write_json(cache_path, data)
        return JSONResponse(data)

    try:
        data = _fetch_weather(geo_cache)
    except Exception as e:
        data = {
            "status": "error",
            "error": str(e),
            "updated_at": _now_iso(),
        }
    _write_json(cache_path, data)
    return JSONResponse(data)


@app.get("/api/holidays")
def holidays(state: str, year: int, mode: str = "refresh") -> JSONResponse:
    state_norm = _normalize_key(state)
    cache_path = _holidays_cache_path(state_norm, int(year))
    cached = _read_json(cache_path)

    if mode == "cache":
        if cached:
            return JSONResponse(cached)
        data = {
            "status": "error",
            "country": "DE",
            "state": state.upper(),
            "year": int(year),
            "error": "cache missing",
            "updated_at": _now_iso(),
        }
        return JSONResponse(data)

    if cached:
        return JSONResponse(cached)

    try:
        data = _fetch_holidays(state, int(year))
    except Exception as e:
        data = {
            "status": "error",
            "country": "DE",
            "state": state.upper(),
            "year": int(year),
            "error": str(e),
            "updated_at": _now_iso(),
        }
    _write_json(cache_path, data)
    return JSONResponse(data)


@app.get("/api/admin/immich-sync")
def immich_sync_status() -> Dict[str, object]:
    return {
        "status": "running" if SYNC_STATE["running"] else "idle",
        "last_started": SYNC_STATE["last_started"],
        "last_finished": SYNC_STATE["last_finished"],
        "last_exit_code": SYNC_STATE["last_exit_code"],
        "last_error": SYNC_STATE["last_error"],
    }


@app.post("/api/admin/immich-sync")
def immich_sync_start() -> JSONResponse:
    with SYNC_LOCK:
        if SYNC_STATE["running"]:
            return JSONResponse({
                "status": "busy",
                "message": "sync already running",
                "last_started": SYNC_STATE["last_started"],
            })
        SYNC_STATE["running"] = True
        SYNC_STATE["last_started"] = _now_iso()
        SYNC_STATE["last_finished"] = None
        SYNC_STATE["last_exit_code"] = None
        SYNC_STATE["last_error"] = None

        thread = threading.Thread(target=_run_immich_sync, daemon=True)
        thread.start()

    return JSONResponse({
        "status": "started",
        "last_started": SYNC_STATE["last_started"],
    })
