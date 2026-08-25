#!/bin/bash
# Change the basic-auth password for beatznbox.wesimplyhome.com.
#
# Run this yourself in a terminal — the password is read from the keyboard with
# echo off, hashed locally, and only the bcrypt hash is sent to the server. The
# plaintext never leaves this machine, never appears in argv (so it stays out of
# `ps` and shell history), and is never printed.
#
# Usage:  ./scripts/set-web-password.sh [username]     (default: beatz)

set -euo pipefail

HOST=root@46.224.176.48
SITE=beatznbox.wesimplyhome.com
USER_NAME="${1:-beatz}"
COST=14   # matches the other hashes already in the Caddyfile

if [ ! -t 0 ]; then
  echo "error: needs a terminal to read the password with echo off." >&2
  echo "Run it directly in a shell, not through a pipe." >&2
  exit 1
fi

echo "Changing the password for '$USER_NAME' on $SITE"
echo

read -rsp "New password: " PW1; echo
read -rsp "Again:        " PW2; echo
echo

if [ "$PW1" != "$PW2" ]; then
  echo "Passwords do not match. Nothing changed." >&2
  exit 1
fi
if [ ${#PW1} -lt 8 ]; then
  echo "Too short — use at least 8 characters. Nothing changed." >&2
  exit 1
fi

echo "Hashing locally (cost $COST, takes a second)..."
# Password goes in on stdin, not argv. Caddy's Go bcrypt reads the 2a/2b prefix
# interchangeably, but the rest of the file uses 2a, so normalise for consistency.
HASH=$(PW="$PW1" python3 -c '
import bcrypt, os, sys
pw = os.environ["PW"].encode()
h = bcrypt.hashpw(pw, bcrypt.gensalt(rounds='"$COST"')).decode()
sys.stdout.write("$2a$" + h.split("$", 2)[2])
')
unset PW1 PW2

if [ -z "$HASH" ]; then
  echo "Hashing failed. Nothing changed." >&2
  exit 1
fi

echo "Updating the Caddyfile..."
HASH="$HASH" USER_NAME="$USER_NAME" SITE="$SITE" \
ssh "$HOST" "HASH='$HASH' USER_NAME='$USER_NAME' SITE='$SITE' bash -s" <<'REMOTE'
set -euo pipefail
CF=/etc/caddy/Caddyfile
BAK="$CF.bak-pw-$(date +%Y-%m-%d-%H%M)"
cp "$CF" "$BAK"
echo "  backed up to $BAK"

python3 - <<PY
import os, re, sys
cf   = "$CF"
user = os.environ["USER_NAME"]
new  = os.environ["HASH"]
site = os.environ["SITE"]

lines = open(cf).read().split("\n")
start = next((i for i, l in enumerate(lines) if l.strip().startswith(site + " ")
              or l.strip() == site + " {"), None)
if start is None:
    sys.exit("could not find the %s site block" % site)

# Stay inside this block — brace depth returns to zero at its end.
depth, target = 0, None
for i in range(start, len(lines)):
    depth += lines[i].count("{") - lines[i].count("}")
    if lines[i].strip().startswith(user + " \$2"):
        target = i
        break
    if depth == 0 and i > start:
        break
if target is None:
    sys.exit("could not find a '%s' credential inside the %s block" % (user, site))

indent = lines[target][:len(lines[target]) - len(lines[target].lstrip())]
lines[target] = indent + user + " " + new
open(cf, "w").write("\n".join(lines))
print("  replaced the hash on line %d" % (target + 1))
PY

if caddy validate --config "$CF" --adapter caddyfile >/dev/null 2>&1; then
  systemctl reload caddy
  echo "  config valid, caddy reloaded"
else
  cp "$BAK" "$CF"
  echo "  !! config invalid — restored the backup, nothing changed" >&2
  exit 1
fi
REMOTE

echo
echo "Done. Verifying the old password no longer works..."
CODE=$(curl -s -o /dev/null -w '%{http_code}' \
  --resolve "$SITE:443:46.224.176.48" \
  -u "$USER_NAME:definitely-not-the-new-password" "https://$SITE/")
if [ "$CODE" = "401" ]; then
  echo "  a wrong password is correctly rejected (401)"
else
  echo "  WARNING: expected 401 for a wrong password, got $CODE" >&2
fi

echo
echo "Now check your new one:"
echo "  curl -s -o /dev/null -w '%{http_code}\\n' -u $USER_NAME:'<your password>' https://$SITE/"
echo "  200 means it worked."
