#!/usr/bin/env bash
# Full local snapshot of the AlaToo AI Consultant project folder.
# Creates a timestamped tar.gz under backups/local/ and keeps the newest $KEEP.
# Safe to run from anywhere; it locates the repo root via its own path.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

KEEP="${KEEP:-10}"
OUT_DIR="$ROOT/backups/local"
mkdir -p "$OUT_DIR"

TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$OUT_DIR/alatoo-local-$TS.tar.gz"

echo "[backup_local] archiving project -> $ARCHIVE"
tar \
  --exclude='./.git' \
  --exclude='./backups' \
  --exclude='./.venv' --exclude='./venv' \
  --exclude='./.pytest_cache' \
  --exclude='./pytest-cache-files-*' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.~lock.*#' \
  -czf "$ARCHIVE" -C "$ROOT" . 2>/dev/null || true

if [ ! -s "$ARCHIVE" ]; then
  echo "[backup_local] ERROR: archive not created" >&2
  exit 1
fi

SIZE_B="$(stat -c %s "$ARCHIVE" 2>/dev/null || wc -c < "$ARCHIVE")"
echo "[backup_local] size: $(( SIZE_B / 1024 / 1024 )) MB ($SIZE_B bytes)"

# record the exact git commit so the snapshot is reproducible
git rev-parse HEAD > "$OUT_DIR/alatoo-local-$TS.gitref" 2>/dev/null || true

# retention: keep newest $KEEP archives (delete may be blocked on some mounts; best-effort)
ls -1t "$OUT_DIR"/alatoo-local-*.tar.gz 2>/dev/null | tail -n +"$((KEEP+1))" | while read -r f; do
  echo "[backup_local] pruning old: $f"
  rm -f "$f" "${f%.tar.gz}.gitref" 2>/dev/null || true
done

echo "[backup_local] done."
