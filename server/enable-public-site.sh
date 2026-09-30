#!/bin/bash
# Open the site: the password stops being the front door and the app's own
# accounts become it. Run ON THE VPS, AS ROOT:
#
#   ssh root@46.224.176.48 bash /opt/beatznbox/enable-public-site.sh
#
# Why (30 Sep): two features need to be reachable by people who do not have
# the password -- the live lyrics link (a stranger in a park taps a link) and
# playlist share links (a new person must be able to sign up). Until this runs,
# both die at Caddy's Sign in box.
#
# What it changes, one line: the basic_auth matcher goes from
# "everything except /sw.js" to "*.mp3 only". So afterwards:
#
#   public      the player, live.html, /api/*, songs.json, the lyrics JSON
#   password    the audio itself -- /stems/<dir>/<stem>.mp3, which is the one
#               thing that must never be publicly downloadable
#
# The audio cannot be pulled by a stranger even with no password, because
# /api/stem-token (which mints the token the R2 edge checks) now requires a
# login, and the bucket itself is private. That gate was deployed with the
# service, not by this script.
#
# The `header_up X-Beatz-User` line is left alone: with basic_auth no longer
# matching, it resolves empty, and the service reads an empty name as nobody --
# which is exactly right. A browser cannot forge it, because header_up
# overwrites whatever the client sent.
#
# Rollback: restore the backup this script prints and reload Caddy.
set -euo pipefail

F=/etc/caddy/Caddyfile
SITE=beatznbox.wesimplyhome.com
STAMP=$(date +%Y%m%d-%H%M%S)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: ssh root@46.224.176.48 bash /opt/beatznbox/enable-public-site.sh" >&2
    exit 1
fi

grep -q "^$SITE {" "$F" || { echo "No '$SITE {' block in $F -- stopping." >&2; exit 1; }

# Already open? Then there is nothing to do, and doing it twice must not
# corrupt the file.
if grep -q '@needsauth path \*.mp3' "$F"; then
    echo "Already open: @needsauth already matches *.mp3 only. Nothing to do."
    exit 0
fi
grep -q '@needsauth not path /sw.js' "$F" || {
    echo "Expected '@needsauth not path /sw.js' in $F and did not find it." >&2
    echo "The Caddyfile has changed shape; look before editing by hand." >&2
    exit 1
}
grep -q 'header_up X-Beatz-User' "$F" || {
    echo "header_up X-Beatz-User is missing from $F -- fix that first (it is" >&2
    echo "what keeps a forged header out once the password is gone)." >&2
    exit 1
}

BAK="$F.bak-before-public-$STAMP"
cp -p "$F" "$BAK"
echo "Backup: $BAK"

NEW=$(mktemp /etc/caddy/.Caddyfile.public.XXXXXX)
trap 'rm -f "$NEW"' EXIT
sed 's|@needsauth not path /sw.js|@needsauth path *.mp3|' "$F" > "$NEW"
chown --reference="$F" "$NEW"
chmod --reference="$F" "$NEW"

if ! caddy validate --config "$NEW" --adapter caddyfile >/dev/null 2>&1; then
    echo "The edited copy does NOT validate -- live Caddyfile untouched:" >&2
    caddy validate --config "$NEW" --adapter caddyfile 2>&1 | tail -n 5 >&2
    exit 1
fi

cp -p "$NEW" "$F"
if ! caddy validate --config "$F" --adapter caddyfile >/dev/null 2>&1 || ! systemctl reload caddy; then
    echo "Live file failed validation or reload -- restoring $BAK" >&2
    cp -p "$BAK" "$F"
    systemctl reload caddy || true
    exit 1
fi

# Verify from the box, by hostname, the two directions that matter: the page
# must answer WITHOUT a password, and an mp3 must still refuse one.
code() { curl -sk -o /dev/null -w '%{http_code}' --max-time 8 \
         -H "Host: $SITE" "https://127.0.0.1$1"; }
fail=0
for pair in "/:200" "/live.html:200" "/api/health:200" "/stems/Aa_Chal_Ke_Tujhe/vocals.mp3:401"; do
    path="${pair%:*}"; want="${pair##*:}"
    got=$(code "$path")
    if [ "$got" = "$want" ]; then
        echo "  ok    $path -> $got"
    else
        echo "  FAIL  $path -> $got (wanted $want)" >&2
        fail=1
    fi
done

if [ "$fail" -ne 0 ]; then
    echo "Something is wrong -- rolling back to $BAK" >&2
    cp -p "$BAK" "$F"
    systemctl reload caddy
    echo "Rolled back. The site is exactly as it was." >&2
    exit 1
fi

echo
echo "The site is open. The password now guards the audio only."
echo "  the player and live links: https://$SITE/"
echo "  rollback:  cp -p $BAK $F && systemctl reload caddy"
echo
echo "Sign in with an ACCOUNT now (add-account.sh), not the old Caddy login."
