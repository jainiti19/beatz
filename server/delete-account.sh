#!/bin/bash
# Delete an ACCOUNT and everything it owns.
#
#   scp server/delete-account.sh beatznbox@46.224.176.48:/tmp/
#   ssh beatznbox@46.224.176.48 'bash /tmp/delete-account.sh tarun'
#
# Removing only the account record would leave the login gone but its
# playlists, shares, share links, clips and saved setups behind -- orphaned
# data nobody can reach and, worse, a stale share link that would come back
# to life as 'no longer valid' answers for ever. This removes it all in one
# go, backs every file up first, and refuses to remove the last admin.
#
# Env overrides (dev/test): BEATZ_USERS_FILE, BEATZ_QUEUE_DIR -- defaults are
# the VPS layout, /opt/beatznbox/users.json and /opt/beatznbox/queue/.
set -euo pipefail

USERS="${BEATZ_USERS_FILE:-/opt/beatznbox/users.json}"
QUEUE="${BEATZ_QUEUE_DIR:-/opt/beatznbox/queue}"
NAME="${1:-}"
if [ -z "$NAME" ]; then
    echo "usage: delete-account.sh <name>" >&2
    exit 1
fi

NAME="$NAME" USERS="$USERS" QUEUE="$QUEUE" python3 - <<'PY'
import json, os, time

name = os.environ['NAME']
users_p = os.environ['USERS']
queue = os.environ['QUEUE']
stamp = time.strftime('%Y%m%d-%H%M%S')
notes = []


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            v = json.load(f)
        return v if isinstance(v, dict) else default
    except Exception:
        return default


def save(path, value, indent=None):
    """Write the way the file's own writer does -- users.json at indent=1,
    the queue files flat -- and keep the original permissions."""
    mode = (os.stat(path).st_mode & 0o777) if os.path.exists(path) else 0o644
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=indent)
    os.chmod(tmp, mode)
    os.replace(tmp, path)          # atomic: a reader never sees a half file


def backup(path):
    if os.path.exists(path):
        with open(path, 'rb') as src, open(path + '.bak-' + stamp, 'wb') as dst:
            dst.write(src.read())


# ---- the account itself ------------------------------------------------
users = load(users_p, {})
accts = users.get('accounts') or {}
rec = accts.get(name)
if not isinstance(rec, dict):
    raise SystemExit('no such account: ' + name)
if rec.get('role') == 'admin' and \
        sum(1 for r in accts.values()
            if isinstance(r, dict) and r.get('role') == 'admin') <= 1:
    raise SystemExit('refusing: that is the last admin')
backup(users_p)
del accts[name]
users['accounts'] = accts
save(users_p, users, indent=1)
notes.append('account removed (role was %s)' % (rec.get('role') or '?'))

# ---- playlists, shares and links ---------------------------------------
pl_p = os.path.join(queue, 'playlists.json')
pl = load(pl_p, {})
if pl:
    backup(pl_p)
    up = pl.get('userPlaylists') or {}
    bucket = up.pop(name, None)
    if bucket is not None:
        notes.append('playlists: ' + (', '.join(sorted(bucket)) or '(none)'))
    shares = pl.get('shares') or {}
    if shares.pop(name, None) is not None:
        notes.append('grants made TO them removed')
    dropped = []
    for recipient, by_owner in list(shares.items()):
        if by_owner.pop(name, None) is not None:
            dropped.append(recipient)
        if not by_owner:
            del shares[recipient]
    if dropped:
        notes.append('grants BY them removed (to: %s)' % ', '.join(sorted(dropped)))
    links = pl.get('shareLinks') or {}
    gone = [t for t, r in links.items()
            if isinstance(r, dict) and r.get('owner') == name]
    for t in gone:
        del links[t]
    if gone:
        notes.append('%d share link(s) removed' % len(gone))
    pl['userPlaylists'] = up
    pl['shares'] = shares
    pl['shareLinks'] = links
    pl['rev'] = int(pl.get('rev') or 0) + 1     # clients reconcile on next load
    save(pl_p, pl)

# ---- clips and saved setups ---------------------------------------------
for fname, label in (('clips.json', 'clips'), ('presets.json', 'setups')):
    p = os.path.join(queue, fname)
    d = load(p, {})
    if not d:
        continue
    backup(p)
    buckets = d.get('__user__') or {}
    bucket = buckets.pop(name, None)
    if bucket is not None:
        notes.append('%d %s removed' % (len(bucket), label))
    if buckets:
        d['__user__'] = buckets
    else:
        d.pop('__user__', None)
    save(p, d)

print('deleted: ' + name)
for n in notes:
    print('  ' + n)
print('backups carry the %s stamp' % stamp)
PY
