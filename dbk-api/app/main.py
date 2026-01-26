import hashlib
import os
import pillow_heif
import subprocess
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from typing import List, Dict, Optional

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
