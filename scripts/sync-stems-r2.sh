#!/bin/bash
# Push anything in web/stems that the R2 bucket does not already hold.
#
# The bucket was originally filled by hand and nothing recorded how, so there
# was no way to add a song to it afterwards. Without this, every song added
# after that upload would quietly be served from Nuremberg while everything
# around it came from the edge -- the player falls back to the origin on a
# 404, so it works, it is just slower for no visible reason.
#
# The existing keys are read through the Worker's own /_keys listing rather
# than guessed, and PAGED: R2 caps a list at 1000 and this library is already
# 651 objects. Compares size, not just presence, so a re-encoded stem is
# re-uploaded.
#
# Usage: ./scripts/sync-stems-r2.sh [--dry-run]
set -uo pipefail

WORKER=${BEATZ_WORKER_URL:-https://beatznbox-stems.itijain.workers.dev}
BUCKET=beatznbox-stems
SRC=web/stems
WRANGLER="npx --yes wrangler@4.86.0"   # newer needs node 22; this laptop is 20
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

cd "$(dirname "$0")/.."
[ -d "$SRC" ] || { echo "no $SRC here"; exit 1; }

TOKEN=$(./scripts/mint-stem-token.py) || { echo "could not mint a token"; exit 1; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

echo "Reading what the bucket already holds..."
CURSOR=""
: > "$TMP/remote.txt"
while :; do
  URL="$WORKER/_keys?limit=1000&t=$TOKEN"
  [ -n "$CURSOR" ] && URL="$URL&cursor=$CURSOR"
  curl -sf --max-time 60 "$URL" > "$TMP/page.json" || { echo "  /_keys failed — is the Worker deployed?"; exit 1; }
  python3 -c "
import json,sys
d=json.load(open('$TMP/page.json'))
for k in d['keys']: print(f\"{k['key']}\t{k['size']}\")
" >> "$TMP/remote.txt"
  CURSOR=$(python3 -c "import json; print(json.load(open('$TMP/page.json')).get('cursor') or '')")
  [ -n "$CURSOR" ] || break
done
echo "  $(wc -l < "$TMP/remote.txt") objects in R2"

python3 - "$SRC" "$TMP/remote.txt" > "$TMP/todo.txt" <<'PY'
import os, sys
src, remote_file = sys.argv[1], sys.argv[2]
remote = {}
for line in open(remote_file):
    k, _, s = line.rstrip('\n').rpartition('\t')
    if k: remote[k] = int(s)
for root, dirs, files in os.walk(src):
    # Never upload wrangler's own droppings, which have appeared under here.
    dirs[:] = [d for d in dirs if not d.startswith('.')]
    for f in files:
        if f.startswith('.'): continue
        p = os.path.join(root, f)
        key = os.path.relpath(p, src)
        if remote.get(key) != os.path.getsize(p):
            print(f"{key}\t{p}")
PY

N=$(wc -l < "$TMP/todo.txt")
if [ "$N" -eq 0 ]; then echo "Bucket is already current."; exit 0; fi
echo "$N file(s) to upload:"
cut -f1 "$TMP/todo.txt" | sed 's/^/  /' | head -20
[ "$N" -gt 20 ] && echo "  ... and $((N - 20)) more"
[ "$DRY" -eq 1 ] && { echo "(dry run — nothing uploaded)"; exit 0; }

ok=0; bad=0
while IFS=$'\t' read -r key path; do
  if $WRANGLER r2 object put "$BUCKET/$key" --file "$path" --remote >/dev/null 2>&1; then
    ok=$((ok+1)); echo "  up  $key"
  else
    bad=$((bad+1)); echo "  ERR $key"
  fi
done < "$TMP/todo.txt"
echo "Uploaded $ok, failed $bad."
[ "$bad" -eq 0 ]
