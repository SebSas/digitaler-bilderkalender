#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SUPPORTED = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}


def _hash_id(container_prefix: str, rel: Path) -> str:
    # Match dbk-api hashing (sha1 of full container path string).
    path_str = f"{container_prefix}/{rel.as_posix()}"
    return hashlib.sha1(path_str.encode("utf-8")).hexdigest()


def _collect_ids(album_dir: Path, container_prefix: str) -> set[str]:
    ids: set[str] = set()
    for p in album_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            rel = p.relative_to(album_dir)
            ids.add(_hash_id(container_prefix, rel))
    return ids


def _prune_dir(cache_dir: Path, valid_ids: set[str]) -> int:
    removed = 0
    if not cache_dir.exists():
        return removed
    for p in cache_dir.glob("*"):
        if not p.is_file():
            continue
        if p.stem not in valid_ids:
            p.unlink()
            removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--album-dir", required=True, help="Host path to the album directory.")
    parser.add_argument("--cache-dir", required=True, help="Host path to dbk-api cache directory.")
    parser.add_argument("--container-prefix", default="/album", help="Album path inside container (default: /album).")
    args = parser.parse_args()

    album_dir = Path(args.album_dir)
    cache_dir = Path(args.cache_dir)
    if not album_dir.exists():
        print(f"Album dir not found: {album_dir}")
        return 2
    if not cache_dir.exists():
        print(f"Cache dir not found: {cache_dir}")
        return 3

    valid_ids = _collect_ids(album_dir, args.container_prefix)
    removed_full = _prune_dir(cache_dir / "full", valid_ids)
    removed_thumb = _prune_dir(cache_dir / "thumb", valid_ids)
    print(f"Prune complete: removed {removed_full} full, {removed_thumb} thumb")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
