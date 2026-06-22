#!/usr/bin/env bash
# Server-side backup of all irreplaceable runtime data on the droplet:
#   1) SQLite chat.db (chat logs + RIASEC results)  -> consistent online copy
#   2) Qdrant storage (alatoo_kb collection)        -> volume tarball
#   3) OpenWebUI data (users + chats)               -> volume tarball
#   4) .env secrets                                 -> encrypted if BACKUP_PASSPHRASE set
# Run ON the droplet:  cd /opt/alatoo-ai-consultant && bash scripts/backup_server.sh
set -euo pipefail

REPO="${REPO:-/opt/alatoo-ai-consultant}"
cd "$REPO"

KEEP="${KEEP:-14}"
TS="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
OUT_DIR="$REPO/backups/server"
mkdir -p "$OUT_DIR"
trap 'rm -rf "$WORK"' EXIT

echo "[backup_server] staging in $WORK"

# 1) SQLite -> consistent online backup via the backend container's Python
echo "[backup_server] (1/4) SQLite online backup..."
docker compose exec -T backend python - <<'PY'
import sqlite3, os
src = os.environ.get("LOG_DB", "/app/logs/chat.db")
dst = "/app/logs/_backup_chat.db"
con = sqlite3.connect(src); bck = sqlite3.connect(dst)
with bck:
    con.backup(bck)
bck.close(); con.close()
print("  online backup ok ->", dst)
PY
CID="$(docker compose ps -q backend)"
docker cp "$CID:/app/logs/_backup_chat.db" "$WORK/chat.db"
docker compose exec -T backend sh -c 'rm -f /app/logs/_backup_chat.db' || true

# 2) Qdrant storage volume (read-only copy)
echo "[backup_server] (2/4) Qdrant volume..."
QVOL="$(docker volume ls -q | grep -E 'qdrant_data$' | head -1 || true)"
if [ -n "$QVOL" ]; then
  docker run --rm -v "$QVOL":/v:ro -v "$WORK":/out alpine \
    tar czf /out/qdrant_data.tar.gz -C /v . && echo "  $QVOL captured"
else
  echo "  WARNING: qdrant_data volume not found (KB is rebuildable via ingestion)"
fi

# 3) OpenWebUI data volume (users + chat history)
echo "[backup_server] (3/4) OpenWebUI volume..."
OWVOL="$(docker volume ls -q | grep -E 'open-webui|openwebui-data' | head -1 || true)"
if [ -n "$OWVOL" ]; then
  docker run --rm -v "$OWVOL":/v:ro -v "$WORK":/out alpine \
    tar czf /out/openwebui_data.tar.gz -C /v . && echo "  $OWVOL captured"
else
  echo "  note: OpenWebUI volume not found, skipping"
fi

# 4) .env secrets
echo "[backup_server] (4/4) .env..."
if [ -f "$REPO/.env" ]; then
  if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
    openssl enc -aes-256-cbc -pbkdf2 -salt -in "$REPO/.env" \
      -out "$WORK/env.enc" -pass pass:"$BACKUP_PASSPHRASE"
    echo "  .env encrypted (AES-256)"
  else
    cp "$REPO/.env" "$WORK/env.plain"
    echo "  WARNING: .env stored UNENCRYPTED -- set BACKUP_PASSPHRASE to encrypt, and keep the archive private"
  fi
else
  echo "  note: no .env at $REPO/.env"
fi

# manifest
{ echo "created: $TS"; echo "host: $(hostname)"; echo "commit: $(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo n/a)"; } > "$WORK/MANIFEST.txt"

ARCHIVE="$OUT_DIR/alatoo-server-$TS.tar.gz"
tar czf "$ARCHIVE" -C "$WORK" .
echo "[backup_server] wrote $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# retention
ls -1t "$OUT_DIR"/alatoo-server-*.tar.gz 2>/dev/null | tail -n +"$((KEEP+1))" | xargs -r rm -f || true
echo "[backup_server] done. Pull it home with scripts/pull_server_backups.sh"
