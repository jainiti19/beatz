#!/bin/bash
# Turn on gzip/zstd for beatznbox.wesimplyhome.com.
#
# Why a script and not a pasted command: long lines wrap in a terminal and
# break, which is how two earlier Caddyfile edits failed.
#
# The site has no `encode` at all, while thegoodruckus.com in the SAME file on
# the SAME box has had `encode gzip zstd` since it was set up. So every first
# visit pulls index.html at 192,893 bytes instead of ~52,799, and songs.json at
# 32,648 instead of ~7,459 -- 220KB where 59KB would do, across 200-600ms to
# Nuremberg. Measured 18 Sep 2026: that is ~3.1s of the startup wait on a bad
# stretch of the link, ~0.1s on a good one.
#
# Caddy here is v2.11.4, whose `encode` already defaults to text content types,
# so mp3s are not touched and no CPU is wasted on them.
#
# Copy it up and run it as root (the Caddyfile is root-owned and the beatznbox
# deploy user has no sudo):
#
#   scp scripts/enable-compression.sh beatznbox@46.224.176.48:/opt/beatznbox/
#   ssh root@46.224.176.48 'bash /opt/beatznbox/enable-compression.sh'
#
set -euo pipefail
CF=/etc/caddy/Caddyfile
ANCHOR='^	root \* /opt/beatznbox/web$'

if [ "$(id -u)" -ne 0 ]; then
  echo "must run as root (the Caddyfile is root-owned)"; exit 1
fi

# Idempotent: re-running it must not stack a second directive.
if awk '/^beatznbox\.wesimplyhome\.com \{/,/^\}/' "$CF" | grep -q '^[[:space:]]*encode '; then
  echo "already enabled — nothing to do"; exit 0
fi

n=$(grep -c "$ANCHOR" "$CF" || true)
if [ "$n" -ne 1 ]; then
  echo "expected exactly 1 anchor line, found $n — aborting rather than guessing"; exit 1
fi

BAK="$CF.bak-encode-$(date +%Y%m%d)"
cp -a "$CF" "$BAK"
echo "backup: $BAK"

# Inserted immediately before THIS site's root line, so it lands inside this
# block and no other. A literal tab, because caddy fmt rewrites indentation
# to tabs and a space-indented line would be reformatted later anyway.
sed -i "/$ANCHOR/i\\	encode gzip zstd" "$CF"

echo "--- the block now reads ---"
awk '/^beatznbox\.wesimplyhome\.com \{/,/^\}/' "$CF" | grep -nE 'encode|root \*|file_server'

# Five other sites share this file. Never reload without validating first.
if ! caddy validate --config "$CF" >/tmp/caddy-validate.log 2>&1; then
  echo "VALIDATE FAILED — restoring the backup and changing nothing:"
  cat /tmp/caddy-validate.log
  cp -a "$BAK" "$CF"
  exit 1
fi
echo "validate: ok"

systemctl reload caddy
sleep 1
systemctl is-active caddy | sed 's/^/caddy: /'

cat <<'EOF'

Check it worked, from anywhere:
  curl -sI -H 'Accept-Encoding: gzip' https://beatznbox.wesimplyhome.com/index.html | grep -i content-encoding

To undo: restore the .bak-encode-* file printed above and reload caddy.
EOF
