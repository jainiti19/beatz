#!/bin/bash
# Create (or update) a BeatznBox ACCOUNT on the VPS: a login the app itself
# checks, with a password this script hashes into /opt/beatznbox/users.json.
#
#   ssh -t root@46.224.176.48 bash /opt/beatznbox/add-account.sh <name> [role]
#
# (-t because it asks for the password; without a terminal it refuses.)
# role is one of viewer, editor, admin and defaults to admin, because the
# reason this exists is seeding the hosts -- see below.
#
# Why accounts and not add-user.sh: that script adds a login to Caddy's
# basic_auth, which identifies a caller for as long as Caddy is the door. When
# the site opens (no more password for the player, so the live-lyrics link and
# share links can be sent to strangers), Caddy stops naming anybody, and these
# accounts become the only way in. Passwords for them are bcrypt, cost 12,
# exactly as the signup form writes them, so the service treats both the same.
#
# Safe to re-run: an existing account keeps its role unless this script is
# what changes it, and the whole users.json is rewritten atomically with every
# other key preserved (users.json also holds the Caddy-login roles, and losing
# those would quietly demote admin).
#
# No restart is needed: the service reads users.json on every request.
set -euo pipefail

USERS=/opt/beatznbox/users.json
STAMP=$(date +%Y%m%d)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: ssh -t root@46.224.176.48 bash /opt/beatznbox/add-account.sh <name> [role]" >&2
    exit 1
fi

NAME="${1:-}"
ROLE="${2:-admin}"
if [ -z "$NAME" ]; then
    echo "Usage: add-account.sh <name> [viewer|editor|admin]" >&2
    exit 1
fi
case "$NAME" in
    *[!A-Za-z0-9_.-]*|'') echo "Name must be letters, digits, dot, dash or underscore." >&2; exit 1 ;;
esac
case "$ROLE" in
    viewer|editor|admin) ;;
    *) echo "Role must be viewer, editor or admin (got '$ROLE')." >&2; exit 1 ;;
esac
if [ "$NAME" = "__user__" ]; then
    echo "That name is reserved by the storage format." >&2
    exit 1
fi

if [ ! -t 0 ]; then
    echo "Needs a terminal to ask for the password. Use ssh -t:" >&2
    echo "  ssh -t root@46.224.176.48 bash /opt/beatznbox/add-account.sh $NAME $ROLE" >&2
    exit 1
fi

while :; do
    read -r -s -p "New password for '$NAME': " PW1; echo
    read -r -s -p "Same again: " PW2; echo
    if [ "${#PW1}" -lt 8 ]; then echo "At least 8 characters -- try again."; continue; fi
    if [ "$PW1" != "$PW2" ]; then echo "They differ -- try again."; continue; fi
    break
done

# The hash is made here, piped in on stdin, so the password never appears in
# any process's arguments.
PW="$PW1" NAME="$NAME" ROLE="$ROLE" USERS="$USERS" python3 - <<'PY'
import json, os, sys, time
import bcrypt                     # the same library and cost the service uses

path, name, role = os.environ['USERS'], os.environ['NAME'], os.environ['ROLE']
pw = os.environ['PW'].encode()

try:
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    if not isinstance(d, dict):
        d = {}
except Exception:
    d = {}
backup = path + '.bak-' + time.strftime('%Y%m%d-%H%M%S')
if os.path.exists(path):
    with open(path, 'rb') as src, open(backup, 'wb') as dst:
        dst.write(src.read())

accts = d.setdefault('accounts', {})
had = name in accts
rec = accts.get(name) if isinstance(accts.get(name), dict) else {}
# Preserve what this script does not manage: a re-run is also the manual
# password-reset path, and forgetting `email` would silently break the
# account's forgot-password route, while forgetting to bump `sess` would let
# every old session cookie survive the reset it was meant to revoke.
accts[name] = dict(
    rec,
    pw=bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode('ascii'),
    role=role,
    created=rec.get('created') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    sess=int(rec.get('sess') or 0) + (1 if had else 0),
)
accts[name].pop('reset', None)

tmp = path + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=1)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print(('updated' if had else 'created') + ': ' + name + ' -> ' + role)
print('backup: ' + (backup if os.path.exists(backup) else 'none (first account)'))
PY

# The service runs as beatznbox and WRITES this file on signup, so it must own
# it -- a root-owned users.json would make every signup fail with a 500.
chown beatznbox:beatznbox "$USERS"
chmod 600 "$USERS"
unset PW1 PW2

echo
echo "Accounts now in $USERS:"
python3 -c "import json;d=json.load(open('$USERS'));print('  ' + '\n  '.join(sorted(d.get('accounts') or {})) or '  (none)')"
echo
echo "Nothing to restart: the service reads users.json on every request."
echo "Sign in at the site with this name and password."
