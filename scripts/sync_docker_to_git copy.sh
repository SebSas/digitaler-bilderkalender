#!/usr/bin/env bash
set -euo pipefail

# -----------------------------
# Config (adjust if needed)
# -----------------------------
SRC_WEB_DIR="${SRC_WEB_DIR:-$HOME/docker/dbk-web}"
SRC_API_DIR="${SRC_API_DIR:-$HOME/docker/dbk-api}"

DEST_REPO_DIR="${DEST_REPO_DIR:-$HOME/git/digitaler-bilderkalender}"
DEST_WEB_DIR="${DEST_WEB_DIR:-$DEST_REPO_DIR/dbk-web}"
DEST_API_DIR="${DEST_API_DIR:-$DEST_REPO_DIR/dbk-api}"

DRY_RUN="${DRY_RUN:-0}"   # set to 1 for a dry run

# -----------------------------
# Helpers
# -----------------------------
die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

require_dir() {
  local d="$1"
  [[ -d "$d" ]] || die "Directory not found: $d"
}

# Common rsync excludes (keep it practical)
RSYNC_EXCLUDES=(
  "--exclude=.git/"
  "--exclude=.DS_Store"
  "--exclude=Thumbs.db"

  "--exclude=node_modules/"
  "--exclude=dist/"
  "--exclude=build/"
  "--exclude=.next/"
  "--exclude=coverage/"
  "--exclude=.cache/"

  "--exclude=__pycache__/"
  "--exclude=.pytest_cache/"
  "--exclude=.mypy_cache/"
  "--exclude=.ruff_cache/"
  "--exclude=.venv/"
  "--exclude=venv/"

  "--exclude=*.log"
)

RSYNC_BASE_ARGS=(
  "-a"                 # archive: perms, times, symlinks, etc.
  "--delete"           # mirror destination to source
  "--human-readable"
  "--info=stats2,progress2"
)

if [[ "$DRY_RUN" == "1" ]]; then
  RSYNC_BASE_ARGS+=("--dry-run")
  info "DRY RUN enabled (no changes will be written)."
fi

# -----------------------------
# Checks
# -----------------------------
require_dir "$SRC_WEB_DIR"
require_dir "$SRC_API_DIR"
require_dir "$DEST_REPO_DIR"

[[ -d "$DEST_REPO_DIR/.git" ]] || die "Destination is not a git repo (missing .git): $DEST_REPO_DIR"

mkdir -p "$DEST_WEB_DIR" "$DEST_API_DIR"

# -----------------------------
# Sync
# -----------------------------
info "Sync dbk-web:  $SRC_WEB_DIR  ->  $DEST_WEB_DIR"
rsync "${RSYNC_BASE_ARGS[@]}" "${RSYNC_EXCLUDES[@]}" "$SRC_WEB_DIR/" "$DEST_WEB_DIR/"

info "Sync dbk-api:  $SRC_API_DIR  ->  $DEST_API_DIR"
rsync "${RSYNC_BASE_ARGS[@]}" "${RSYNC_EXCLUDES[@]}" "$SRC_API_DIR/" "$DEST_API_DIR/"

info "Done."
info "Tip: run 'git status' in $DEST_REPO_DIR to review changes."
