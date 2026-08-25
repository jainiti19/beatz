#!/bin/bash
# Publish the web player to beatznbox.wesimplyhome.com (Hetzner VPS).
#
# Mirrors web/ to the VPS as the unprivileged 'beatznbox' user. The site sits
# behind basic auth in Caddy — see /etc/caddy/Caddyfile on the host. Static
# files only; nothing on the server is a source of record, so a full re-push
# is always safe.
#
# Usage:
#   ./scripts/deploy-web.sh              # mirror web/ to the server
#   ./scripts/deploy-web.sh --dry-run    # show what would change, send nothing
#
# Re-run after prepare-web.sh whenever songs or lyrics change.

set -euo pipefail

HOST=beatznbox@46.224.176.48
DEST=/opt/beatznbox/web/
SRC="$(cd "$(dirname "$0")/../web" && pwd)/"

DRY=""
if [ "${1:-}" = "--dry-run" ]; then
  DRY="--dry-run"
  echo "DRY RUN — nothing will be transferred"
fi

if [ ! -f "$SRC/index.html" ]; then
  echo "error: $SRC/index.html not found — wrong directory?" >&2
  exit 1
fi

echo "Publishing $SRC -> $HOST:$DEST"
du -sh "$SRC" | awk '{print "  local size: " $1}'

# --delete keeps the server an exact mirror, so songs removed locally stop
# being served. mp3 is already compressed, so -z would burn CPU for nothing.
# progress2 draws a live counter, which is only readable on a terminal — in a
# log or a pipe it emits one line per update. Fall back to a per-file summary.
if [ -t 1 ]; then PROGRESS="--info=progress2"; else PROGRESS="--info=stats2"; fi

rsync -rlt --delete --partial --human-readable $PROGRESS $DRY \
  --exclude='.*' \
  --exclude='*.whisper-bak' \
  --exclude='__pycache__' \
  "$SRC" "$HOST:$DEST"

if [ -z "$DRY" ]; then
  echo
  echo "Published. Remote size:"
  ssh "$HOST" "du -sh $DEST; find $DEST -name '*.mp3' | wc -l | xargs echo '  mp3 files:'"
  echo
  echo "Live at https://beatznbox.wesimplyhome.com"
fi
