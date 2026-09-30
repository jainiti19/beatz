#!/bin/bash
# Add a login to beatznbox.wesimplyhome.com and record what it may do.
# Run ON THE VPS, AS ROOT, interactively:
#
#     ssh -t root@46.224.176.48 bash /opt/beatznbox/add-user.sh <name> [role]
#
# (-t because it asks for the password; without a terminal it refuses.)
# role is one of viewer, editor, admin and defaults to editor.
#
# Why (30 Sep): the site had two logins, `beatz` for everyone and `admin` for
# Iti and Karan, and playlists were one shared file. That is fine for a night
# but not for a library: a tester who wants their own set has nowhere to put
# it, and giving them `admin` to get one hands them the shared set too. So a
# login now carries a ROLE, and an `editor` may write their own playlists,
# setups and clips without touching anyone else's.
#
# Two edits, both inside the beatznbox.wesimplyhome.com block ONLY -- five
# other sites share this Caddyfile:
#
#   1. basic_auth gains `<name> <bcrypt hash>` beside the existing logins.
#   2. /opt/beatznbox/users.json gains {"<name>": {"role": "<role>"}}.
#
# The password is typed at the prompt, piped to `caddy hash-password` by the
# shell's builtin printf (never a command-line argument, so never visible in
# ps), and only the hash is written anywhere.
#
# Safe to run twice: an existing login's password is kept unless you choose to
# replace it, and its role is updated in place. The edited Caddyfile is
# validated as a copy BEFORE it replaces the live one, then the live one is
# validated again before the reload; any failure puts the backup back and
# exits non-zero.
#
# ORDER MATTERS when deploying: run this BEFORE restarting queue-service.py
# with the roles change. The new service reads users.json on every request, so
# a login added here takes effect immediately; the OLD service ignores the
# file entirely, so adding a user first is harmless. Rollback is the reverse:
# service first, then remove the login from the Caddyfile by hand.
set -euo pipefail

F=/etc/caddy/Caddyfile
SITE=beatznbox.wesimplyhome.com
USERS=/opt/beatznbox/users.json
STAMP=$(date +%Y%m%d)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: ssh -t root@46.224.176.48 bash /opt/beatznbox/add-user.sh <name> [role]" >&2
    exit 1
fi

NAME="${1:-}"
ROLE="${2:-editor}"
if [ -z "$NAME" ]; then
    echo "Usage: add-user.sh <name> [viewer|editor|admin]" >&2
    exit 1
fi
case "$NAME" in
    *[!A-Za-z0-9_.-]*|'') echo "Name must be letters, digits, dot, dash or underscore." >&2; exit 1 ;;
esac
case "$ROLE" in
    viewer|editor|admin) ;;
    *) echo "Role must be viewer, editor or admin (got '$ROLE')." >&2; exit 1 ;;
esac

reload_checked() {
    # Validate the LIVE file, then reload. Caddy keeps serving the old config
    # if a reload fails, but a validate first means we never ask it to.
    caddy validate --config "$F" --adapter caddyfile >/dev/null 2>&1 || return 1
    systemctl reload caddy
}

if [ ! -t 0 ]; then
    echo "Needs a terminal to ask for the password. Use ssh -t:" >&2
    echo "  ssh -t root@46.224.176.48 bash /opt/beatznbox/add-user.sh $NAME $ROLE" >&2
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
HAVE_USER=no; grep -Eq "^[[:space:]]+$NAME [$]2" <<<"$BLOCK" && HAVE_USER=yes

SET_PW=yes
if [ "$HAVE_USER" = yes ]; then
    read -r -p "A login '$NAME' already exists. Replace its password? [y/N] " a
    case "$a" in y|Y|yes) SET_PW=yes ;; *) SET_PW=no ;; esac
fi

USER_HASH=""
if [ "$SET_PW" = yes ]; then
    while :; do
        read -r -s -p "New password for '$NAME': " PW1; echo
        read -r -s -p "Same again: " PW2; echo
        if [ -z "$PW1" ]; then echo "Empty -- try again."; continue; fi
        if [ "$PW1" != "$PW2" ]; then echo "They differ -- try again."; continue; fi
        break
    done
    # printf is a bash builtin: the password goes down a pipe, never into
    # any process's argv. bcrypt, the same as the existing logins.
    USER_HASH=$(printf '%s\n' "$PW1" | caddy hash-password --algorithm bcrypt 2>/dev/null)
    unset PW1 PW2
    case "$USER_HASH" in '$2'*) ;; *) echo "caddy hash-password gave no bcrypt hash -- stopping." >&2; exit 1 ;; esac
fi

# ---- backup (house convention: Caddyfile.bak-<reason>-<date>) -------------
BAK="$F.bak-user-$NAME-$STAMP"
[ -e "$BAK" ] && BAK="$F.bak-user-$NAME-$STAMP-$(date +%H%M%S)"
cp -p "$F" "$BAK"
echo "Backup: $BAK"

# ---- edit a copy ------------------------------------------------------------
NEW=$(mktemp /etc/caddy/.Caddyfile.user.XXXXXX)
trap 'rm -f "$NEW"' EXIT
USER_HASH="$USER_HASH" NAME="$NAME" SITE="$SITE" python3 - "$F" "$NEW" <<'PY'
import os, re, sys
src, dst = sys.argv[1], sys.argv[2]
site, name, h = os.environ['SITE'], os.environ['NAME'], os.environ['USER_HASH']
lines = open(src, encoding='utf-8').read().split('\n')

# The site block: its opening line to the first column-0 "}" after it.
start = lines.index(site + ' {')
end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('}'))
body = lines[start:end + 1]

# The login, beside the others, with the same indentation (caddy fmt uses
# tabs; copying an existing login line's leading whitespace follows whatever
# is there). Replaced in place if it exists, so there is only ever one.
if h:
    existing = [i for i, l in enumerate(body) if re.match(r'\s+' + re.escape(name) + r' \$2', l)]
    if existing:
        indent = re.match(r'\s*', body[existing[0]]).group(0)
        body[existing[0]] = indent + name + ' ' + h
        for i in reversed(existing[1:]):
            del body[i]
    else:
        # Insert after the last existing login line, so the block stays tidy.
        logins = [i for i, l in enumerate(body) if re.match(r'\s+\S+ \$2[aby]\$', l)]
        if not logins:
            sys.exit('no existing basic_auth login lines in the block to sit beside')
        indent = re.match(r'\s*', body[logins[-1]]).group(0)
        body.insert(logins[-1] + 1, indent + name + ' ' + h)

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

# ---- record the role --------------------------------------------------------
# Written AFTER Caddy accepts the login: a role for a login that cannot
# authenticate is harmless, but a login with no role would fall back to the
# admins() rule and could come out stronger than intended.
ROLE="$ROLE" NAME="$NAME" USERS="$USERS" python3 - <<'PY'
import json, os, tempfile
path, name, role = os.environ['USERS'], os.environ['NAME'], os.environ['ROLE']
try:
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
except Exception:
    d = {}
users = d.get('users') if isinstance(d.get('users'), dict) else {}
users[name] = {'role': role}
d['users'] = users
os.makedirs(os.path.dirname(path), exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=1)
os.replace(tmp, path)
print(f"  users.json: {name} -> {role}")
PY

echo "RELOADED. The beatznbox block now reads:"
block | grep -nE '^[[:space:]]*(basic_auth|beatz |admin |'"$NAME"' |reverse_proxy|header_up)' | sed -E 's/(\$2[aby]\$[0-9]+\$).{53}/\1.../' || true
echo
echo "Restart the queue service so it picks up the new role:"
echo "  systemctl restart beatznbox-queue   # or: /opt/beatznbox/restart-queue.sh"
