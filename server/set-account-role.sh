#!/bin/bash
# Change an ACCOUNT's role (viewer|editor|admin) in /opt/beatznbox/users.json.
#
# Run it on the VPS as the service's owner (it writes users.json, which is
# beatznbox-owned because signup writes it too):
#
#   scp server/set-account-role.sh beatznbox@46.224.176.48:/tmp/
#   ssh beatznbox@46.224.176.48 'bash /tmp/set-account-role.sh karan editor'
#
# Safe to re-run. It backs users.json up first, refuses to demote the LAST
# admin (with no admin left nobody can change the shared set), and bumps the
# account's session epoch so any device already signed in as that person
# comes back with the new role immediately -- a demoted admin would otherwise
# keep admin powers until their 30-day cookie expired. No restart needed:
# the service reads users.json on every request.
set -euo pipefail

USERS=/opt/beatznbox/users.json
NAME="${1:-}"
ROLE="${2:-}"
case "$ROLE" in
    viewer|editor|admin) ;;
    *) echo "usage: set-account-role.sh <name> <viewer|editor|admin>" >&2; exit 1 ;;
esac
if [ -z "$NAME" ]; then
    echo "usage: set-account-role.sh <name> <viewer|editor|admin>" >&2
    exit 1
fi

NAME="$NAME" ROLE="$ROLE" USERS="$USERS" python3 - <<'PY'
import json, os, time

name, role, path = os.environ['NAME'], os.environ['ROLE'], os.environ['USERS']
with open(path, encoding='utf-8') as f:
    d = json.load(f)
accts = d.get('accounts') or {}
if name not in accts:
    raise SystemExit('no such account: ' + name)
if role != 'admin' and (accts[name].get('role') == 'admin') and \
        sum(1 for r in accts.values()
            if isinstance(r, dict) and r.get('role') == 'admin') <= 1:
    raise SystemExit('refusing: that would leave no admin')

backup = path + '.bak-' + time.strftime('%Y%m%d-%H%M%S')
with open(path, 'rb') as src, open(backup, 'wb') as dst:
    dst.write(src.read())

rec = accts[name]
rec['role'] = role
rec['sess'] = int(rec.get('sess') or 0) + 1     # sign their old devices out
accts[name] = rec
d['accounts'] = accts

tmp = path + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=1)
os.chmod(tmp, 0o600)
os.replace(tmp, path)       # atomic: the service never sees a half-written file

print('backup: ' + backup)
print('now: ' + ', '.join(sorted(
    '%s=%s' % (k, (v.get('role') if isinstance(v, dict) else '?'))
    for k, v in accts.items())))
PY
