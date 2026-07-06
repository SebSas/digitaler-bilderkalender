#!/usr/bin/env python3
"""Minimal Immich album downloader for the DBK sync (Immich v3 compatible).

Replaces ghcr.io/zckyachmd/immich-album-downloader, which broke with Immich v3
(album response no longer embeds assets). Uses only the Python standard
library. Reads IMMICH_BASE_URL and IMMICH_API_KEY from the environment.

Usage: immich_album_sync.py --album "Album Name" --dest /path/to/dir
Exit code 0 only if every asset of the album was downloaded.
"""
import argparse
import json
import os
import sys
import urllib.request


def api(base: str, key: str, path: str, payload=None):
    req = urllib.request.Request(
        base + path, headers={"x-api-key": key, "Accept": "application/json"}
    )
    if payload is not None:
        req.data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--album", required=True)
    parser.add_argument("--dest", required=True)
    args = parser.parse_args()

    base = os.environ["IMMICH_BASE_URL"].rstrip("/")
    key = os.environ["IMMICH_API_KEY"]

    albums = api(base, key, "/api/albums") + api(base, key, "/api/albums?shared=true")
    ids = {a["id"] for a in albums if a.get("albumName") == args.album}
    if not ids:
        names = sorted({a.get("albumName", "?") for a in albums})
        sys.exit(f"Album {args.album!r} not found. Visible albums: {names}")
    album_id = ids.pop()

    assets = []
    page = 1
    while True:
        res = api(
            base, key, "/api/search/metadata",
            {"albumIds": [album_id], "size": 500, "page": page},
        )
        block = res.get("assets", {})
        assets.extend(block.get("items", []))
        if not block.get("nextPage"):
            break
        page = int(block["nextPage"])

    print(f"Album {args.album!r}: {len(assets)} assets")
    os.makedirs(args.dest, exist_ok=True)

    seen = set()
    downloaded = 0
    for asset in assets:
        name = asset.get("originalFileName") or f"{asset['id']}.bin"
        if name.lower() in seen:
            stem, dot, ext = name.rpartition(".")
            name = f"{stem}-{asset['id'][:8]}.{ext}" if dot else f"{name}-{asset['id'][:8]}"
        seen.add(name.lower())

        req = urllib.request.Request(
            f"{base}/api/assets/{asset['id']}/original", headers={"x-api-key": key}
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp, \
                    open(os.path.join(args.dest, name), "wb") as out:
                while chunk := resp.read(1 << 16):
                    out.write(chunk)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"FAILED {name}: {exc}")
            continue
        downloaded += 1
        print(f"downloaded {name}")

    print(f"Done: {downloaded}/{len(assets)} downloaded")
    if downloaded == 0 or downloaded < len(assets):
        sys.exit(1)


if __name__ == "__main__":
    main()
