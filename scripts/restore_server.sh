#!/usr/bin/env bash
# Restore server data from an archive produced by backup_server.sh.
# Run ON the droplet:
#   cd /opt/alatoo-ai-consultant && bash scripts/restore_server.sh backups/server/alatoo-server-YYYYMMDD-HHMMSS.tar.gz
set -euo pipefail

REPO="${REPO:-/opt/alatoo-ai-consultant}"
ARCHIVE="${1:?usage: restore_server.sh <archive.tar.gz>}"
cd "$REPO"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar xzf "$ARCHIVE" -C "$WORK"

echo "[restore] manifest:"; cat "$WORK/MANIFEST.txt" 2>/dev/null || true
read -r -p "This OVERWRITES current SQLite / Qdrant / OpenWebUI data. Continue? [yes/NO] " ok
[ "$ok" = "yes" ] || { echo "aborted"; exit 1; }

echo "[restore] stopping stack..."
docker compose down

QVOL="$(docker volume ls -q | grep -E 'qdrant_data$' | head -1 || true)"
if [ -f "$WORK/qdrant_data.tar.gz" ] && [ -n "$QVOL" ]; then
  echo "[restore] Qdrant volume..."
  docker run --rm -v "$QVOL":/v -v "$WORK":/in alpine \
    sh -c 'rm -rf /v/* && tar xzf /in/qdrant_data.tar.gz -C /v'
fi

OWVOL="$(docker volume ls -q | grep -E 'open-webui|openwebui-data' | head -1 || true)"
if [ -f "$WORK/openwebui_data.tar.gz" ] && [ -n "$OWVOL" ]; then
  echo "[restore] OpenWebUI volume..."
  docker run --rm -v "$OWVOL":/v -v "$WORK":/in alpine \
    sh -c 'rm -rf /v/* && tar xzf /in/openwebui_data.tar.gz -C /v'
fi

echo "[restore] starting stack..."
docker compose up -d
sleep 8

if [ -f "$WORK/chat.db" ]; then
  echo "[restore] SQLite chat.db..."
  CID="$(docker compose ps -q backend)"
  docker cp "$WORK/chat.db" "$CID:/app/logs/chat.db"
  docker compose restart backend
fi

if [ -f "$WORK/env.enc" ]; then
  echo "[restore] .env is ENCRYPTED. Decrypt manually:"
  echo "  tar xzO -f \"$ARCHIVE\" ./env.enc | openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:'YOUR_PASSPHRASE' > $REPO/.env"
elif [ -f "$WORK/env.plain" ]; then
  cp "$WORK/env.plain" "$REPO/.env"
  echo "[restore] .env restored. Recreate backend to load it: docker compose up -d --force-recreate backend"
fi

echo "[restore] done. Verify: curl -s https://chat.alatoogpt.xyz/healthz"
