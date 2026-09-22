#!/bin/bash
# Add the `admin` login to beatznbox.wesimplyhome.com and tell the queue
# service who is logged in. Run ON THE VPS, AS ROOT, interactively:
#
#     ssh -t root@46.224.176.48 bash /opt/beatznbox/enable-admin-login.sh
#
# (-t because it asks for the password; without a terminal it refuses.)
# Undo with the same command plus --rollback.
#
# Why (23 Sep, for Music Night on Fri 25 Sep): Karan's medleys are shared
# playlists with clips he timed by ear, and the site is also open to testers
# in Hong Kong and elsewhere under the one `beatz` login. From now on `beatz`
# can play, request, report and paste lyrics but not change the shared
# playlists, setups or clips; `admin` (Iti and Karan) keeps everything. The
# refusal itself lives in server/queue-service.py -- this script only gives
# it the login name to decide on.
#
# Two edits, both inside the beatznbox.wesimplyhome.com block ONLY -- five
# other sites share this Caddyfile:
#
#   1. basic_auth gains `admin <bcrypt hash>` beside `beatz`.
#   2. `reverse_proxy /api/* 127.0.0.1:8931` becomes
#          reverse_proxy /api/* 127.0.0.1:8931 {
#              header_up X-Beatz-User {http.auth.user.id}
#          }
#      header_up with a value SETS the header, replacing any a browser sent
#      under that name, so nobody can claim to be admin by sending it
#      themselves. The service listens on 127.0.0.1 only, so Caddy is the
#      only way in from outside.
#
# The password is typed at the prompt, piped to `caddy hash-password` by the
# shell's builtin printf (never a command-line argument, so never visible in
# ps), and only the hash is written anywhere.
#
# Safe to run twice: an existing admin line is kept unless you choose to
# replace its password, and the header edit is never added twice. The
# edited file is validated as a copy BEFORE it replaces the live one, then
# the live one is validated again before the reload; any failure puts the
# backup back and exits non-zero.
#
# ORDER MATTERS when deploying: run this BEFORE copying the new
# queue-service.py over and restarting it. The new service treats a request
# that came through Caddy without a login name as a viewer (fail closed), so
# the new service without this edit locks EVERYONE, admin included, out of
# editing. The old service simply ignores the new header, so this edit first
# is harmless. Rollback is the reverse: service first, then --rollback.
set -euo pipefail

F=/etc/caddy/Caddyfile
SITE=beatznbox.wesimplyhome.com
STAMP=$(date +%Y%m%d)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: ssh -t root@46.224.176.48 bash /opt/beatznbox/enable-admin-login.sh" >&2
    exit 1
fi

reload_checked() {
    # Validate the LIVE file, then reload. Caddy keeps serving the old config
    # if a reload fails, but a validate first means we never ask it to.
    caddy validate --config "$F" --adapter caddyfile >/dev/null 2>&1 || return 1
    systemctl reload caddy
}

# ---- rollback -------------------------------------------------------------
if [ "${1:-}" = "--rollback" ]; then
    # The OLDEST roles backup is the file as it was before this script ever
    # ran (later runs make time-stamped ones, never overwrite it).
    B=$(ls -1 "$F".bak-roles-* 2>/dev/null | sort | head -n1 || true)
    if [ -z "$B" ]; then echo "No $F.bak-roles-* backup found; nothing to roll back." >&2; exit 1; fi
    cp "$F" "$F.bak-roles-undone-$(date +%Y%m%d-%H%M%S)"
    cp "$B" "$F"
    if reload_checked; then
        echo "ROLLED BACK to $B and reloaded Caddy."
        echo "Remember: the new queue-service.py treats no-login-name as a viewer."
        echo "Put the pre-roles service back first, or nobody can edit playlists."
        exit 0
    fi
    echo "Rollback file $B did not validate -- live file left as that copy; check by hand." >&2
    exit 1
fi

if [ ! -t 0 ]; then
    echo "Needs a terminal to ask for the password. Use ssh -t:" >&2
    echo "  ssh -t root@46.224.176.48 bash /opt/beatznbox/enable-admin-login.sh" >&2
    exit 1
fi

grep -q "^$SITE {" "$F" || { echo "No '$SITE {' block in $F -- stopping." >&2; exit 1; }

# ---- what is already there ------------------------------------------------
# Awk prints the site block's lines only: from "beatznbox.wesimplyhome.com {"
# to the first "}" at column 0 after it.
block() { awk -v s="$SITE {" '$0==s{on=1} on{print} on&&/^}/{exit}' "$F"; }

# Captured once rather than piped into grep -q: under pipefail, grep -q
# quitting early can SIGPIPE awk and turn a match into a "no".
BLOCK=$(block)
HAVE_ADMIN=no;  grep -Eq '^[[:space:]]+admin [$]2' <<<"$BLOCK" && HAVE_ADMIN=yes
HAVE_HEADER=no; grep -q 'X-Beatz-User' <<<"$BLOCK" && HAVE_HEADER=yes

SET_PW=yes
if [ "$HAVE_ADMIN" = yes ]; then
    read -r -p "An admin login already exists. Replace its password? [y/N] " a
    case "$a" in y|Y|yes) SET_PW=yes ;; *) SET_PW=no ;; esac
fi

if [ "$SET_PW" = no ] && [ "$HAVE_HEADER" = yes ]; then
    echo "Already set up: admin login and X-Beatz-User header both present. Nothing to do."
    exit 0
fi

ADMIN_HASH=""
if [ "$SET_PW" = yes ]; then
    while :; do
        read -r -s -p "New password for the admin login: " PW1; echo
        read -r -s -p "Same again: " PW2; echo
        if [ -z "$PW1" ]; then echo "Empty -- try again."; continue; fi
        if [ "$PW1" != "$PW2" ]; then echo "They differ -- try again."; continue; fi
        break
    done
    # printf is a bash builtin: the password goes down a pipe, never into
    # any process's argv. bcrypt, the same as the existing beatz line.
    ADMIN_HASH=$(printf '%s\n' "$PW1" | caddy hash-password --algorithm bcrypt 2>/dev/null)
    unset PW1 PW2
    case "$ADMIN_HASH" in '$2'*) ;; *) echo "caddy hash-password gave no bcrypt hash -- stopping." >&2; exit 1 ;; esac
fi

# ---- backup (house convention: Caddyfile.bak-<reason>-<date>) -------------
# Never overwrite an earlier backup from today: the first one is the
# pre-roles file and is what --rollback restores.
BAK="$F.bak-roles-$STAMP"
[ -e "$BAK" ] && BAK="$F.bak-roles-$STAMP-$(date +%H%M%S)"
cp -p "$F" "$BAK"
echo "Backup: $BAK"

# ---- edit a copy ------------------------------------------------------------
NEW=$(mktemp /etc/caddy/.Caddyfile.roles.XXXXXX)
trap 'rm -f "$NEW"' EXIT
ADMIN_HASH="$ADMIN_HASH" SITE="$SITE" python3 - "$F" "$NEW" <<'PY'
import os, re, sys
src, dst = sys.argv[1], sys.argv[2]
site, h = os.environ['SITE'], os.environ['ADMIN_HASH']
lines = open(src, encoding='utf-8').read().split('\n')

# The site block: its opening line to the first column-0 "}" after it.
start = lines.index(site + ' {')
end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('}'))
body = lines[start:end + 1]

# 1. admin login, beside beatz, with the same indentation (caddy fmt uses
#    tabs; copying the beatz line's leading whitespace follows whatever is
#    there). Replaced in place if it exists, so there is only ever one.
if h:
    beatz = [i for i, l in enumerate(body) if re.match(r'\s+beatz \$2', l)]
    if len(beatz) != 1:
        sys.exit('expected exactly one "beatz $2..." line in the block, found %d' % len(beatz))
    indent = re.match(r'\s*', body[beatz[0]]).group(0)
    admin = [i for i, l in enumerate(body) if re.match(r'\s+admin \$2', l)]
    if admin:
        body[admin[0]] = indent + 'admin ' + h
        for i in reversed(admin[1:]):
            del body[i]
    else:
        body.insert(beatz[0] + 1, indent + 'admin ' + h)

# 2. the login name to the queue service. Only the exact bare directive is
#    rewritten; if it already has a { ... } block, stop rather than guess.
if not any('X-Beatz-User' in l for l in body):
    rp = [i for i, l in enumerate(body)
          if l.strip() == 'reverse_proxy /api/* 127.0.0.1:8931']
    if len(rp) != 1:
        sys.exit('expected exactly one bare "reverse_proxy /api/* 127.0.0.1:8931" line, found %d' % len(rp))
    i = rp[0]
    ind = re.match(r'\s*', body[i]).group(0)
    step = '\t' if ind.startswith('\t') or not ind else ' ' * len(ind)
    body[i:i + 1] = [
        ind + '# X-Beatz-User: which login this is, for the queue service to',
        ind + '# tell admin (Iti, Karan) from beatz (testers). header_up with a',
        ind + '# value REPLACES any the browser sent -- it cannot be spoofed.',
        ind + '# Added 23 Sep by enable-admin-login.sh, for Music Night 25 Sep.',
        ind + 'reverse_proxy /api/* 127.0.0.1:8931 {',
        ind + step + 'header_up X-Beatz-User {http.auth.user.id}',
        ind + '}',
    ]

lines[start:end + 1] = body
with open(dst, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
PY

# Keep the live file's owner and mode on the copy that replaces it.
chown --reference="$F" "$NEW"; chmod --reference="$F" "$NEW"

if ! caddy validate --config "$NEW" --adapter caddyfile >/dev/null 2>&1; then
    echo "The edited copy does NOT validate -- live Caddyfile untouched:" >&2
    caddy validate --config "$NEW" --adapter caddyfile 2>&1 | tail -n 5 >&2
    exit 1
fi

cp -p "$NEW" "$F"
if ! reload_checked; then
    echo "Live file failed validation or reload -- restoring $BAK" >&2
    cp -p "$BAK" "$F"
    systemctl reload caddy || true
    exit 1
fi

echo "RELOADED. The beatznbox block now reads:"
block | grep -nE '^[[:space:]]*(basic_auth|beatz |admin |reverse_proxy|header_up)' | sed -E 's/(\$2[aby]\$[0-9]+\$).{53}/\1.../' || true
echo
echo "Rollback: ssh -t root@46.224.176.48 bash /opt/beatznbox/enable-admin-login.sh --rollback"
