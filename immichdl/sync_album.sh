#!/usr/bin/env bash
set -euo pipefail

# Album name in Immich (shared with the DBK user) - may differ from the
# local folder name, which is baked into the dbk-api compose mount.
IMMICH_ALBUM="Digi Bilderkalender Ana"
ALBUM_NAME="Digi Bilderkalender Ana"
IMAGE="ghcr.io/zckyachmd/immich-album-downloader:latest"
ENV_FILE="/home/sebi/immichdl/.env"
DOCKER_USER="$(id -u):$(id -g)"

DEST_BASE="/mnt/picstorage/picstorage-album"
DEST="${DEST_BASE}/${ALBUM_NAME}"
TMP="/mnt/picstorage/.picstorage-album.tmp"
MEDIA_CACHE="${TMP}/.media-cache"

rm -rf "$TMP" || {
  echo "Failed to clear temp dir: $TMP"
  exit 1
}
mkdir -p "$TMP"
mkdir -p "$MEDIA_CACHE"

# Local downloader (Immich v3 compatible); the previous docker image
# (immich-album-downloader) broke with v3's album API.
set -a
. "$ENV_FILE"
set +a
python3 /home/sebi/immichdl/immich_album_sync.py \
  --album "$IMMICH_ALBUM" --dest "$TMP/$IMMICH_ALBUM"

# Never mirror an empty download over the existing album (e.g. album name
# mismatch or share revoked) - that would wipe the local snapshot.
downloaded=$(find "$TMP" -path "$MEDIA_CACHE" -prune -o -type f -print | wc -l)
if [ "$downloaded" -eq 0 ]; then
  echo "No files downloaded - aborting without touching $DEST"
  rm -rf "$TMP"
  exit 1
fi
echo "Downloaded $downloaded files"

# Replace contents without deleting the bound directory itself.
mkdir -p "$DEST"
if ! find "$DEST" -mindepth 1 -exec rm -rf {} +; then
  echo "Failed to clear $DEST (permissions). Run: sudo chown -R $(id -u):$(id -g) \"$DEST\""
  exit 1
fi

if [ -d "$TMP/$IMMICH_ALBUM" ]; then
  shopt -s dotglob nullglob
  for item in "$TMP/$IMMICH_ALBUM"/*; do
    mv "$item" "$DEST"/
  done
  shopt -u dotglob nullglob
else
  shopt -s dotglob nullglob
  for item in "$TMP"/*; do
    mv "$item" "$DEST"/
  done
  shopt -u dotglob nullglob
fi

rm -rf "$TMP"

# Prune dbk-api cache entries for files removed from the album.
ALBUM_DIR="$DEST"
CACHE_DIR="/cache"
if [ ! -d "$CACHE_DIR" ]; then
  CACHE_DIR="/home/sebi/docker/dbk-api/cache"
fi
if [ -d "$ALBUM_DIR" ]; then
  python3 /home/sebi/immichdl/prune_cache.py \
    --album-dir "$ALBUM_DIR" \
    --cache-dir "$CACHE_DIR" \
    --container-prefix "/album"
else
  echo "Album dir not found: $ALBUM_DIR"
fi

# Flush filesystem buffers so a later USB hiccup cannot roll back the mirror.
sync
echo "Filesystem flushed"

# Pre-warm the WebP cache (full + thumb) right after a sync so the first
# display/swipe never triggers HEIC conversion storms that starve the API
# healthcheck (observed: kiosk restarts on fast swiping through fresh images).
echo "Warming image cache ..."
for id in $(curl -s http://127.0.0.1:8080/api/images | python3 -c "import json,sys; print('\n'.join(x['id'] for x in json.load(sys.stdin)))" 2>/dev/null); do
  curl -s -o /dev/null --max-time 60 "http://127.0.0.1:8080/api/image/$id" || echo "warm failed: image/$id"
  curl -s -o /dev/null --max-time 60 "http://127.0.0.1:8080/api/thumb/$id" || echo "warm failed: thumb/$id"
done
echo "Cache warm."
sync
