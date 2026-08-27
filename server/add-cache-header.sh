#!/bin/bash
# Tell browsers to keep stem mp3s for a week, so replaying a song costs no
# network. Deliberately not `immutable`: prepare-web.sh re-encodes to the same
# filename when a song is reprocessed, so a year-long entry would pin stale
# audio with no way to bust it.
set -e
F=/etc/caddy/Caddyfile
if grep -q '@audio' "$F"; then echo "already there"; exit 0; fi
cp "$F" "$F.bak-$(date +%Y%m%d-%H%M%S)"
sed -i "s|^\troot \* /opt/beatznbox/web|\t@audio path *.mp3\n\theader @audio Cache-Control public,max-age=604800\n\n&|" "$F"
cd /etc/caddy
caddy validate --config Caddyfile
systemctl reload caddy
echo RELOADED
grep -n -A1 '@audio' "$F"
