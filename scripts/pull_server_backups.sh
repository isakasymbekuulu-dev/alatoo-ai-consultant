#!/usr/bin/env bash
# Pull server-side backup archives from the droplet down to the local project.
# Run on your own machine (needs SSH access to the droplet).
# Usage: DEPLOY_HOST=167.172.176.33 DEPLOY_USER=root bash scripts/pull_server_backups.sh
set -euo pipefail

HOST="${DEPLOY_HOST:?set DEPLOY_HOST, e.g. 167.172.176.33}"
SSH_USER="${DEPLOY_USER:-root}"
REMOTE="${REMOTE_PATH:-/opt/alatoo-ai-consultant/backups/server}"
PORT="${DEPLOY_PORT:-22}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/backups/server"
mkdir -p "$DEST"

echo "[pull] $SSH_USER@$HOST:$REMOTE -> $DEST"
rsync -avz -e "ssh -p $PORT" --progress "$SSH_USER@$HOST:$REMOTE/" "$DEST/"
echo "[pull] done. Local server backups:"
ls -1t "$DEST"/alatoo-server-*.tar.gz 2>/dev/null | head -5 || echo "  (none yet)"
