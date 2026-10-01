#!/usr/bin/env python3
"""Accept song requests from the web player and append them to a queue file.

Runs on the VPS, bound to localhost only — Caddy reverse-proxies /api/ to it,
so every request has already passed the site's basic auth. Caddy also names
the login in X-Beatz-User; since 23 Sep only an admin login may write the
shared playlists, setups and clips (see "who may change the shared set").

Since 30 Sep there are three roles, not two. `admin` keeps everything;
`editor` may write their OWN playlists, setups and clips but not the shared
set; `viewer` is read-only. Roles live in users.json beside the queue files
(see "roles"), and the password stays in Caddy — server/add-user.sh adds a
login there and records its role here.

Also since 30 Sep, people can make their OWN account: POST /api/signup takes
a name and a password, stores a bcrypt hash in users.json under "accounts",
and sets a signed session cookie. Those accounts are separate from the Caddy
logins above: a Caddy login is authenticated by Caddy and arrives as
X-Beatz-User, an account is authenticated here. A session cookie wins over
the header when both are present. New accounts see only their own playlists,
setups and clips; the shared set stays with the Caddy logins, unchanged.

Run with --dev to test on a laptop: no Caddy, so X-Beatz-User is ignored and
the session cookie is the only way in, and the player is served from --web.

The queue is a JSONL file rather than a database because the consumer is a
laptop polling over SSH, and a text file is something you can read, fix by hand
and recover from. Nothing here processes a song; it only records the ask.

Usage: queue-service.py [--port 8931] [--queue /opt/beatznbox/queue/requests.jsonl]
"""
import argparse, base64, hashlib, hmac, json, os, re, secrets, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRESETS_LOCK = threading.Lock()
CLIPS_LOCK = threading.Lock()
# Playlists gained a lock with share links: the file carries a shares map and
# link tokens beside the playlists, and a write that drops one of those loses a
# grant, not just a song list. Lock order, if these ever nest: PLAYLISTS_LOCK
# first, then PRESETS_LOCK/CLIPS_LOCK, never the reverse.
PLAYLISTS_LOCK = threading.Lock()
# users.json is read-modify-written by signup and by /api/users, which also
# share one ".tmp" name -- two at once could interleave inside that file or
# lose an account. SESSION_KEY_LOCK covers the same first-use window for the
# cookie signing key.
USERS_LOCK = threading.Lock()
SESSION_KEY_LOCK = threading.Lock()

# Signs the short-lived tokens that let the R2 Worker serve audio from the
# edge. Read at every mint rather than cached, so rotating the file takes
# effect without a restart -- and so a missing file fails closed instead of
# serving a token signed with something stale.
TOKEN_KEY_PATH = os.environ.get('BEATZ_TOKEN_KEY', '/opt/beatznbox/stem-token.key')
TOKEN_TTL = 7 * 24 * 3600     # a week; the page refreshes on every load

# Where the audio is served from, handed to the player rather than compiled
# into it. The workers.dev hostname carries an account subdomain nobody should
# have to remember, and a player holding a stale one would fail in a way that
# looks like an outage. One file on the box decides it; an empty or missing
# file means there is no edge and the player uses the origin.
EDGE_BASE_PATH = os.environ.get('BEATZ_EDGE_BASE', '/opt/beatznbox/stem-edge.url')

# ---- who may change the shared set -----------------------------------
# Two logins from 23 Sep, for the 25 Sep Music Night: Karan's medleys are
# three shared playlists with twelve clips timed by ear, and the same site is
# open to testers in Hong Kong and elsewhere under the one `beatz` login. One
# stray tap on a delete cross or "Set end" from a tester's phone would rewrite
# the set Karan rehearsed. So `beatz` can do everything EXCEPT write the
# shared state (playlists, saved setups, clips), and a separate `admin` login
# -- Iti and Karan -- keeps today's powers.
#
# Caddy does the authenticating and tells us who with X-Beatz-User, set by
# `header_up X-Beatz-User {http.auth.user.id}` in the reverse_proxy block.
# header_up with a value REPLACES whatever the browser sent under that name,
# so a client cannot claim to be admin through Caddy -- and this service
# listens on 127.0.0.1 only, so nothing reaches it except through Caddy or
# from the box itself. See server/enable-admin-login.sh.
#
# Which logins count as admin, first match wins:
#   1. BEATZ_ADMINS env var, comma-separated ("admin,karan"), set in the
#      systemd unit with Environment=
#   2. /opt/beatznbox/admins.txt (BEATZ_ADMINS_FILE to move it), one login
#      per line, # comments allowed
#   3. just "admin"
# Read on every request, like the token key, so adding a login to the file
# takes effect without a restart.
ADMINS_FILE = os.environ.get('BEATZ_ADMINS_FILE', '/opt/beatznbox/admins.txt')
DEFAULT_ADMINS = {'admin'}

# Per-user roles, so a login can own playlists without being an admin. Kept
# beside the queue files, like playlists.json, because that is where the data
# it scopes already lives. Read on every request (like the token key and the
# admins file) so adding a user takes effect without a restart.
#
# Shape: {"users": {"iti": {"role": "editor"}, "karan": {"role": "admin"}}}
# A login absent from this file falls back to the admins() rule below, so the
# existing `admin` and `beatz` logins keep working with no migration.
# Where users.json lives. Defaults to the queue directory (set in main() from
# --queue), so a --dev run keeps every file it writes under one scratch
# directory and never touches /opt/beatznbox. BEATZ_USERS_FILE overrides it,
# which is what the VPS uses.
USERS_FILE = os.environ.get('BEATZ_USERS_FILE', '')

# The key that signs session cookies. Deliberately NOT the stem-token key: a
# stem token is handed to a browser to fetch audio, and if one leaked it must
# not also be a login. Generated on first use, 0600, beside the other keys.
# Same rule as USERS_FILE: beside the queue files unless overridden.
SESSION_KEY_FILE = os.environ.get('BEATZ_SESSION_KEY_FILE', '')

# The mail sender: {host, port, user, password, from, notify, base}. Holds an
# SMTP password, so it lives 0600 beside users.json and is read per send
# (rotating it needs no restart). Missing file = mail is simply not set up:
# reset links say so honestly, signup notifications are skipped, and nothing
# else changes. BEATZ_MAIL_SPOOL (dev and tests) writes messages to a file
# instead of sending, so the round trip is testable without a mailbox.
MAIL_FILE = os.environ.get('BEATZ_MAIL_FILE', '/opt/beatznbox/mail.json')
MAIL_SPOOL = os.environ.get('BEATZ_MAIL_SPOOL', '')

# How long a login lasts. Long, because this is a party app and nobody wants
# to type a password every time they open it; the cookie is HttpOnly and the
# site is behind Caddy, so the exposure is small. A password change or a
# reset bumps the account's session epoch and outdates every existing cookie,
# which is what makes that acceptable.
SESSION_TTL = 30 * 24 * 3600

# A reset link. Short, because it is a password in a URL: it sits in a mailbox
# (and in mail-server logs) and one leak should be worth minutes, not a day.
RESET_TTL = 30 * 60

# Signup and login are the only endpoints an unauthenticated caller can reach,
# so they are the only ones worth guessing at. A small in-memory counter per
# IP blunts that without a dependency. Not a substitute for fail2ban.
AUTH_ATTEMPTS = {}          # ip -> [timestamps]
AUTH_ATTEMPTS_LOCK = threading.Lock()
AUTH_MAX = 10               # attempts
AUTH_WINDOW = 15 * 60       # seconds

# Forgot-password gets its OWN budget, counted over ALL calls (a send is the
# abuse, not just a failure). Sharing AUTH_ATTEMPTS would mean ten forgotten
# passwords from one NAT -- a household -- locking everyone out of LOGIN.
FORGOT_ATTEMPTS = {}        # ip -> [timestamps]
FORGOT_ATTEMPTS_LOCK = threading.Lock()
FORGOT_MAX = 5
FORGOT_WINDOW = 15 * 60

# The password rule (1 Oct). Deliberately modest: the room is family and
# friends, so it blocks the embarrassing cases -- too short, the user name
# itself, "password123" -- without demanding a password manager. The byte cap
# is not taste: bcrypt 5 RAISES past 72 bytes, so without it a long signup
# password kills the request rather than being refused politely.
PW_MIN = 8
PW_MAX_BYTES = 72

# The usual suspects, lower-case. A sing-along app does not need zxcvbn; it
# needs "password" and "12345678" to stop being someone's karaoke password.
COMMON_PASSWORDS = frozenset((
    '123456', 'password', '12345678', 'qwerty', '123456789', '12345', '1234',
    '111111', '1234567', 'dragon', '123123', 'baseball', 'abc123', 'football',
    'monkey', 'letmein', 'shadow', 'master', '666666', 'qwertyuiop', '123321',
    'mustang', '1234567890', 'michael', '654321', 'superman', '1qaz2wsx',
    '7777777', '121212', '000000', 'qazwsx', '123qwe', 'killer', 'trustno1',
    'jordan', 'jennifer', 'zxcvbnm', 'asdfgh', 'hunter', 'buster', 'soccer',
    'harley', 'batman', 'andrew', 'tigger', 'sunshine', 'iloveyou', '2000',
    'charlie', 'robert', 'thomas', 'hockey', 'ranger', 'daniel', 'starwars',
    'klaster', '112233', 'george', 'computer', 'michelle', 'jessica', 'pepper',
    '1111', 'zxcvbn', '555555', '11111111', '131313', 'freedom', '777777',
    'pass', 'maggie', '159753', 'aaaaaa', 'ginger', 'princess', 'joshua',
    'cheese', 'amanda', 'summer', 'love', 'ashley', '6969', 'nicole',
    'chelsea', 'biteme', 'matthew', 'access', 'yankees', '987654321', 'dallas',
    'austin', 'thunder', 'taylor', 'matrix', 'william', 'corvette', 'hello',
    'martin', 'heather', 'secret', 'merlin', 'diamond', '1234abcd', 'virginia',
    'bear', 'tiger', 'cookie', 'whatever', 'qazwsxedc', '12121212', 'letmein1',
    'welcome', 'welcome1', 'admin', 'admin123', 'root', 'toor', 'passw0rd',
    'p@ssw0rd', 'abc12345', '1q2w3e4r', 'qwerty123', 'qwerty1', '123456a',
    'zaq12wsx', 'qazxsw', 'asdfasdf', 'asdf1234', 'iloveyou1', 'monkey1',
    'dragon1', 'baseball1', 'football1', 'princess1', 'sunshine1', 'michael1',
    'charlie1', 'jordan23', 'jennifer1', 'maggie1', 'ginger1', 'hunter1',
    'summer1', 'chelsea1', 'matthew1', 'computer1', 'michelle1', 'jessica1',
    'pepper1', 'daniel1', 'thomas1', 'robert1', 'andrew1', 'tigger1',
    'batman1', 'ranger1', 'hockey1', 'soccer1', 'buster1', 'harley1',
    'starwars1', 'mustang1', 'shadow1', 'master1', 'superman1', 'trustno1!',
    'killer1', 'secret1', 'merlin1', 'diamond1', 'virginia1', 'whatever1',
    'welcome123', 'hello123', 'india123', 'india', 'delhi', 'mumbai', 'krishna',
    'ganesh', 'shiva', 'password1', 'password12', 'password123', 'pass1234',
    'test1234', 'testing', 'testtest', 'temp1234', 'changeme', 'letmein123',
    'beatz', 'beatznbox',
))


def valid_password(user, pw):
    """None when the password is allowed, else a reason to show the person.
    The reasons are user-facing words, not codes."""
    if not isinstance(pw, str) or len(pw) < PW_MIN:
        return f'Password must be at least {PW_MIN} characters.'
    if len(pw.encode('utf-8')) > PW_MAX_BYTES:
        return f'Password must be at most {PW_MAX_BYTES} bytes.'
    if len(user) >= 3 and user.lower() in pw.lower():
        return 'Password must not contain your user name.'
    if pw.lower() in COMMON_PASSWORDS:
        return 'That password is too common — pick something else.'
    return None

# Set by --dev. In dev there is no Caddy in front, so X-Beatz-User cannot be
# trusted and the session cookie is the only way in. It also relaxes the
# cookie's Secure flag, since localhost is plain http.
DEV = False

# Where the player's files live, for --dev. Set from --web in main().
WEB_DIR = '/opt/beatznbox/web'

# The reserved key under which per-user presets and clips live inside their
# otherwise-flat files. It contains no "::", so it can never collide with a
# real "<playlist>::<song>" key.
USER_PRESETS_KEY = '__user__'
USER_CLIPS_KEY = '__user__'

# Sharing (30 Sep). A playlist in someone's own bucket can be shared with other
# logins BY LINK: the owner creates a view link or an edit link, and whoever
# opens it claims it -- which needs a login, so the link is an invitation
# rather than an anonymous grant. The grant itself lives in `shares` inside
# playlists.json, beside the playlists it describes, so a delete and its
# cleanup are one atomic write.
SHARE_ROLES = ('view', 'edit')  # what a link, or a person, may be granted
MAX_SHARES_IN = 200             # playlists shared TO one login
MAX_SHARES_PER_PLAYLIST = 50    # links + people on one playlist
SHARE_SCOPE = 'share'           # the scope value a collaborator's write carries

# A SHARED-set playlist is owned by the house, not by a login, so a share of
# one is recorded under this sentinel owner. It is not a valid login name
# (no "@" in the charset), so it can never collide with a real user. An admin
# may share a house playlist -- the admin account sees ONLY the shared set, so
# without this it could never share anything at all.
SHARED_OWNER = '@shared'

# Roles, weakest first. `editor` may write their OWN playlists, presets and
# clips; `admin` may also write the shared set and manage users. `viewer` is
# read-only, which is what `beatz` has been since 23 Sep.
ROLES = ('viewer', 'editor', 'admin')


def admins():
    env = os.environ.get('BEATZ_ADMINS')
    if env is not None:
        return {n.strip() for n in env.split(',') if n.strip()}
    try:
        with open(ADMINS_FILE, encoding='utf-8') as f:
            names = {l.split('#', 1)[0].strip() for l in f}
        names.discard('')
        return names
    except OSError:
        return set(DEFAULT_ADMINS)


def users():
    """{login: role} from users.json, or {} when the file is absent.

    A missing or unreadable file is not an error: the service then falls back
    to admins() for every login, which is exactly how it behaved before this
    file existed."""
    try:
        with open(USERS_FILE, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return {}
    out = {}
    for name, rec in (d.get('users') or {}).items():
        if not isinstance(name, str) or not name.strip():
            continue
        role = rec.get('role') if isinstance(rec, dict) else rec
        if role in ROLES:
            out[name.strip()] = role
    return out


def role_of(login):
    """The role for a login name, or None when the login is unknown.

    users.json wins when it names the login; otherwise the admins() rule
    decides, so `admin` stays admin and `beatz` stays a viewer without either
    being written into the new file."""
    if not login:
        return None
    known = users()
    if login in known:
        return known[login]
    if login in admins():
        return 'admin'
    return 'viewer'


# ---- sharing -------------------------------------------------------------
# Pure functions over the two maps in playlists.json ("shares" and
# "shareLinks"). They take the maps as arguments rather than reading files so
# they can be unit-tested on their own, and so a handler can hold one read of
# the file and answer everything from it.

def valid_code(code):
    """A live session code: the random string in a live link. Checked by shape
    so a hand-written path cannot become one."""
    return bool(code) and isinstance(code, str) and 8 <= len(code) <= 32 \
        and re.fullmatch(r'[A-Za-z0-9_-]+', code) is not None


def valid_login(name):
    """A login name. Both kinds of login are restricted to the same charset --
    add-user.sh's Caddy logins and the signup form -- so one predicate covers
    both. It says nothing about whether the name exists: Caddy logins are not
    visible to this service, so an invitation to a name that has not signed up
    yet is allowed and simply waits."""
    return bool(name) and isinstance(name, str) and len(name) <= 40 \
        and re.fullmatch(r'[A-Za-z0-9_.-]+', name) is not None


def valid_owner(owner):
    """A share owner: a login name, or the sentinel that stands for the
    shared set itself. The two cannot collide -- the sentinel fails
    valid_login -- which is what makes '@shared' safe as a dictionary key
    beside real logins in `shares` and `shareLinks`."""
    return owner == SHARED_OWNER or valid_login(owner)


def share_role(shares, user, owner, name):
    """'view' | 'edit' | None: what `user` may do with `owner`'s `name`."""
    if not user or not owner or not name or user == owner:
        return None
    rec = ((shares.get(user) or {}).get(owner) or {}).get(name)
    return rec if rec in SHARE_ROLES else None


def visible_shares(user_pl, shared_pl, shares, user):
    """({name: {'owner', 'role'}}, [shadowed]) for playlists shared to `user`.

    Visible means the owner still HAS that playlist: a login's own bucket, or
    the shared set for a sentinel-owned share. A share whose name the
    caller also owns is SHADOWED -- their own playlist wins, and it is
    reported rather than quietly ignored, so deleting their own brings the
    share back. Dangling shares (owner gone, playlist deleted by hand) are
    skipped quietly: they are the debris of a delete."""
    mine = user_pl.get(user, {}) if user else {}
    meta, shadowed = {}, []
    for owner, by_name in (shares.get(user) or {}).items():
        if not isinstance(by_name, dict):
            continue
        for name, role in by_name.items():
            if role not in SHARE_ROLES:
                continue
            if name in mine or name in meta:
                # Their own playlist, or a second owner sharing the same name:
                # one entry per name keeps the client's bare keys unambiguous.
                shadowed.append({'name': name, 'owner': owner, 'role': role})
                continue
            if owner == SHARED_OWNER:
                if name not in shared_pl:
                    continue            # the house deleted it; the share is dead
            elif name not in (user_pl.get(owner) or {}):
                continue                # the owner deleted it; the share is dead
            meta[name] = {'owner': owner, 'role': role}
    return meta, shadowed


def owned_shares(shares, user):
    """{name: {recipient: role}} for playlists `user` owns."""
    out = {}
    for recipient, by_owner in (shares or {}).items():
        for name, role in ((by_owner or {}).get(user) or {}).items():
            if role in SHARE_ROLES:
                out.setdefault(name, {})[recipient] = role
    return out


def prune_shares_for(shares, links, owner, keep):
    """Grants and links for playlists that no longer exist go with them: a
    link to a deleted playlist must die with the playlist, or re-creating the
    same name later would silently resurrect every old grant and link. `keep`
    is the set of names in the owner's newly-written map; `shares` and `links`
    are mutated in place."""
    for recipient, by_owner in list(shares.items()):
        held = by_owner.get(owner)
        if not isinstance(held, dict):
            continue
        for gone in [n for n in list(held) if n not in keep]:
            del held[gone]
        if not held:
            del by_owner[owner]
        if not by_owner:
            del shares[recipient]
    for token in [t for t, r in links.items()
                  if isinstance(r, dict) and r.get('owner') == owner
                  and r.get('name') not in keep]:
        del links[token]


def key_playlist(key):
    """The playlist half of a "<playlist>::<song>" (or "<playlist>::*") key."""
    return key.rsplit('::', 1)[0] if isinstance(key, str) and '::' in key else ''


def merge_shared_entries(own, other, names):
    """`own` plus every entry of `other` whose playlist half is in `names`.
    Own wins a clash, and `setdefault` is what makes that so."""
    out = dict(own or {})
    for k, v in (other or {}).items():
        if isinstance(k, str) and key_playlist(k) in names:
            out.setdefault(k, v)
    return out


def shared_entries(buckets, shared_buckets, user_pl, shared_pl, shares, user):
    """{key: value} taken from the owners' buckets, for every playlist shared
    to `user` -- clips and presets alike. A sentinel-owned share reads the
    shared set's own maps instead. The keys are the same bare
    "<name>::<song>" the caller already uses for their own, so nothing
    downstream needs to know who owns a playlist."""
    meta, _ = visible_shares(user_pl, shared_pl, shares, user)
    by_owner = {}
    for name, m in meta.items():
        by_owner.setdefault(m['owner'], set()).add(name)
    out = {}
    for owner, names in by_owner.items():
        src = shared_buckets if owner == SHARED_OWNER else (buckets.get(owner) or {})
        out = merge_shared_entries(out, src, names)
    return out


def scope_allowed(scope, user, role, srole):
    """None when a write may proceed, else (http_code, error).

    shared -> admin only. user -> a login that may edit its own; a viewer
    login is refused, which is what `beatz` has been since 23 Sep. share ->
    an edit grant on the playlist named in the body, which even a viewer login
    may hold: the link IS the invitation, and it grants exactly that one
    playlist and nothing else."""
    if scope == 'shared':
        return None if role == 'admin' else (403, 'read-only')
    if scope == 'user':
        if not user:
            return (400, 'no login to own this')
        return None if role != 'viewer' else (403, 'read-only')
    if scope == SHARE_SCOPE:
        return None if srole == 'edit' else (403, 'read-only')
    return (400, 'scope must be shared, user or share')


# ---- accounts ------------------------------------------------------------
# A real account, with a password the person chose, as opposed to the Caddy
# logins above. Kept in the same users.json, under a different key, so the
# two systems share one file and one reader. The Caddy logins have no "pw"
# and are never checked here; they are authenticated by Caddy and arrive as
# X-Beatz-User. An account has a "pw" and is authenticated by this service.
#
# Shape: {"users": {"iti": {"role": "admin"}},
#         "accounts": {"karan": {"pw": "$2b$12$...", "role": "editor",
#                                "created": "2026-09-30T12:00:00Z"}}}
ACCOUNTS_KEY = 'accounts'


def accounts():
    """{login: record} from users.json's "accounts" map, or {}."""
    try:
        with open(USERS_FILE, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return {}
    a = d.get(ACCOUNTS_KEY)
    return a if isinstance(a, dict) else {}


def _write_users(d):
    """Write users.json atomically, 0600: it holds password hashes."""
    tmp = USERS_FILE + '.tmp'
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, USERS_FILE)


def _read_users_file():
    try:
        with open(USERS_FILE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def hash_password(pw):
    """bcrypt, cost 12. Imported lazily so the service still starts (and the
    Caddy logins still work) on a box where bcrypt is not installed yet.

    Cut at PW_MAX_BYTES before hashing: bcrypt 5 RAISES past 72 bytes instead
    of truncating like the C libraries did, and a crash must not be reachable
    from a signup form. valid_password refuses such passwords up front, so
    the cut only ever sees legacy input -- and check_password cuts the same
    bytes, so an old long password still verifies."""
    import bcrypt
    return bcrypt.hashpw(pw.encode('utf-8')[:PW_MAX_BYTES],
                         bcrypt.gensalt(rounds=12)).decode('ascii')


def check_password(pw, hashed):
    import bcrypt
    try:
        return bcrypt.checkpw(pw.encode('utf-8')[:PW_MAX_BYTES],
                              hashed.encode('ascii'))
    except Exception:
        return False


def session_key():
    """The signing key, generated on first use. Read on every call (like the
    stem key) so rotating it takes effect without a restart.

    Read RAW, never stripped: the key is 32 random bytes, and .strip() silently
    dropped the last byte whenever it happened to be whitespace -- cookies were
    then signed with 32 bytes and verified with 31, so about one generated key
    in forty made every later login fail. (Found by looping test_auth.py until
    it failed: one run in twenty-five, and the same shape of flake had already
    cost a browser test an afternoon.) Generation is under a lock and lands with
    os.replace, so a reader never sees a half-written or empty file either."""
    try:
        with open(SESSION_KEY_FILE, 'rb') as f:
            k = f.read()
        if k:
            return k
    except OSError:
        pass
    with SESSION_KEY_LOCK:
        try:                    # another thread may have written it while we waited
            with open(SESSION_KEY_FILE, 'rb') as f:
                k = f.read()
            if k:
                return k
        except OSError:
            pass
        k = secrets.token_bytes(32)
        os.makedirs(os.path.dirname(SESSION_KEY_FILE), exist_ok=True)
        tmp = SESSION_KEY_FILE + '.tmp'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(k)
        os.replace(tmp, SESSION_KEY_FILE)   # atomic: a reader never sees it empty
        return k


def make_session(user, epoch=0):
    """v2.<user>.<epoch>.<exp>.<hmac>. The user is base64url'd so a name with
    a dot in it cannot be mistaken for the separator. `epoch` is the account's
    session counter: changing or resetting a password bumps it, which is what
    outdates every cookie minted before -- the only way a stateless signed
    cookie can be revoked."""
    exp = int(time.time()) + SESSION_TTL
    u = base64.urlsafe_b64encode(user.encode('utf-8')).decode('ascii').rstrip('=')
    msg = f'v2.{u}.{int(epoch or 0)}.{exp}'
    sig = hmac.new(session_key(), msg.encode('ascii'), hashlib.sha256).hexdigest()
    return f'{msg}.{sig}'


def read_session(value):
    """(login, epoch) in a session cookie, or (None, None) if it is absent,
    malformed, expired or not signed by us.

    The v1 shape (no epoch) still verifies: it reads as epoch 0, which every
    account was at until change/reset existed, so cookies already in browsers
    keep working -- they simply die at that account's first password change.
    The calling code decides what a stale epoch means; this function does not
    know the accounts file."""
    if not value:
        return None, None
    parts = value.split('.')
    if len(parts) == 4 and parts[0] == 'v1':
        _, u, exp, sig = parts
        msg, epoch = f'v1.{u}.{exp}', 0
    elif len(parts) == 5 and parts[0] == 'v2':
        _, u, ep, exp, sig = parts
        msg = f'v2.{u}.{ep}.{exp}'
        try:
            epoch = int(ep)
        except ValueError:
            return None, None
    else:
        return None, None
    want = hmac.new(session_key(), msg.encode('ascii'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, want):
        return None, None
    try:
        if int(exp) < time.time():
            return None, None
        pad = '=' * (-len(u) % 4)
        return base64.urlsafe_b64decode(u + pad).decode('utf-8'), epoch
    except Exception:
        return None, None


def auth_check(ip):
    """False when this IP has already failed too many signup/login attempts.

    A check only: failures are counted by auth_record afterwards, so signing
    in and out while testing never uses up a person's own budget."""
    now = time.time()
    with AUTH_ATTEMPTS_LOCK:
        hits = [t for t in AUTH_ATTEMPTS.get(ip, []) if now - t < AUTH_WINDOW]
        AUTH_ATTEMPTS[ip] = hits
        return len(hits) < AUTH_MAX


def auth_record(ip):
    """Count one FAILED attempt against this IP."""
    now = time.time()
    with AUTH_ATTEMPTS_LOCK:
        hits = [t for t in AUTH_ATTEMPTS.get(ip, []) if now - t < AUTH_WINDOW]
        hits.append(now)
        AUTH_ATTEMPTS[ip] = hits
        # Keep the map from growing without bound on a long-running box.
        if len(AUTH_ATTEMPTS) > 1000:
            for k in [k for k, v in AUTH_ATTEMPTS.items()
                      if not [t for t in v if now - t < AUTH_WINDOW]]:
                AUTH_ATTEMPTS.pop(k, None)


def forgot_check(ip):
    """False when this IP has asked for too many reset mails. Counted over ALL
    calls, not just misses: here the SEND is what needs bounding, and unlike
    login a success is not self-limiting."""
    now = time.time()
    with FORGOT_ATTEMPTS_LOCK:
        hits = [t for t in FORGOT_ATTEMPTS.get(ip, []) if now - t < FORGOT_WINDOW]
        FORGOT_ATTEMPTS[ip] = hits
        return len(hits) < FORGOT_MAX


def forgot_record(ip):
    now = time.time()
    with FORGOT_ATTEMPTS_LOCK:
        hits = [t for t in FORGOT_ATTEMPTS.get(ip, []) if now - t < FORGOT_WINDOW]
        hits.append(now)
        FORGOT_ATTEMPTS[ip] = hits
        if len(FORGOT_ATTEMPTS) > 1000:
            for k in [k for k, v in FORGOT_ATTEMPTS.items()
                      if not [t for t in v if now - t < FORGOT_WINDOW]]:
                FORGOT_ATTEMPTS.pop(k, None)


# ---- mail (1 Oct) ----------------------------------------------------------
# Password resets and signup notifications leave through here. Best effort by
# design: signup works for everyone, mail only when a sender is configured,
# and a mail that cannot leave the box never fails the request that wanted it.
def mail_config():
    """The parsed mail.json, or None when mail is not set up."""
    try:
        with open(MAIL_FILE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def send_mail(to, subject, text):
    """True when the message went (or was spooled). Never raises."""
    if not to:
        return False
    cfg = mail_config()
    if MAIL_SPOOL:
        # Dev and tests: no mailbox, but the message is inspectable. JSONL so
        # an assertion is json.loads(last_line), not MIME archaeology.
        try:
            with open(MAIL_SPOOL, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'to': to, 'from': (cfg or {}).get('from', ''),
                                    'subject': subject, 'text': text,
                                    'ts': int(time.time())},
                                   ensure_ascii=False) + '\n')
            return True
        except OSError:
            return False
    if not cfg or not cfg.get('host'):
        return False
    try:
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg['From'] = cfg.get('from') or cfg.get('user') or ''
        msg['To'] = to
        msg['Subject'] = subject
        msg.set_content(text)
        port = int(cfg.get('port') or 465)
        if cfg.get('tls', True):
            server = smtplib.SMTP_SSL(cfg['host'], port, timeout=10)
        else:
            server = smtplib.SMTP(cfg['host'], port, timeout=10)
        with server:
            if cfg.get('user'):
                server.login(cfg['user'], cfg.get('password') or '')
            server.send_message(msg)
        return True
    except Exception as e:
        print(f'mail: could not send to {to}: {e}', flush=True)
        return False


# ---- invites (1 Oct) -------------------------------------------------------
# Signup is gated on a code an admin made: the site is public now, and an open
# signup form on a public site is an invitation to bots. Codes are read aloud
# and typed from screenshots, so the alphabet drops every lookalike.
INVITE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'


def new_invite_code():
    raw = ''.join(secrets.choice(INVITE_ALPHABET) for _ in range(8))
    return raw[:4] + '-' + raw[4:]


def normalize_invite(code):
    return str(code or '').strip().upper()


def valid_email(value):
    """Shape only -- it is a reset channel, not an identity. Deliberately
    forgiving; a typo is found when the reset mail does not arrive."""
    return bool(value) and isinstance(value, str) and len(value) <= 100 \
        and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value) is not None


# ---- live lyrics (30 Sep) ------------------------------------------------
# The host's player publishes what it is playing; a follower who has the link
# polls it and works out where the song is NOW. Deliberately not a socket:
# this service is http.server with no async, a singalong tolerates about a
# second of lag, and the follower extrapolates between polls -- so only the
# phase is refreshed, not every movement. The reply carries the AGE of the
# snapshot rather than a timestamp, so a follower whose clock is wrong still
# lands on the right line.
#
# A session is one login, keyed by a random code that IS the credential: there
# is no listing endpoint, and a stopped session is gone.
LIVE_TTL = 15 * 60          # no update for this long and the session is over
LIVE_MAX = 50               # sessions kept; the oldest go first
LIVE_LOCK = threading.Lock()

MAX_BODY = 4096          # a request is a song name, not a payload
MAX_LYRICS = 32768       # a long song is a few KB; this is generous
MAX_FIELD = 120
MAX_PENDING = 50         # a full queue means something is wrong upstream
MAX_NOTE = 300           # a fault report is a sentence, not an essay

# What a listener can tell us is wrong. Kept as a fixed set rather than free
# text because the four cases need different repairs: a wrong recording needs
# re-downloading, wrong words need refetching, bad sound needs re-separating.
# The note is where anything else goes.
REPORT_REASONS = {'wrong-song', 'lyrics', 'quality', 'other'}

# The published manifest, used only to answer "do we already have this?".
# Read fresh when its mtime changes: the watcher rewrites it on every deploy.
MANIFEST = '/opt/beatznbox/web/stems/songs.json'
_known = {'mtime': None, 'by_key': {}}


def norm(text):
    """Loose key for duplicate detection: case, spaces and punctuation dropped.
    'Tu Kisi Rail Si', 'tu kisi rail si' and 'TuKisiRailSi' all collapse."""
    return re.sub(r'[^a-z0-9]+', '', (text or '').lower())


def known_songs():
    try:
        m = os.path.getmtime(MANIFEST)
    except OSError:
        return {}
    if _known['mtime'] != m:
        try:
            with open(MANIFEST, encoding='utf-8') as f:
                songs = json.load(f)
        except Exception:
            return _known['by_key']
        by_key = {}
        for song in songs:
            for key in (song.get('name'), song.get('dir'),
                        (song.get('dir') or '').replace('_', ' ')):
                if norm(key):
                    by_key.setdefault(norm(key), song.get('name') or song.get('dir'))
        _known['by_key'] = by_key
        _known['mtime'] = m
    return _known['by_key']

# The name becomes a directory, and is interpolated into shell and Python by
# the pipeline. Everything downstream assumes this character set — see the
# matching sanitiser in add-songs.sh.
def slug(text):
    s = re.sub(r'[^A-Za-z0-9_]+', '_', text).strip('_')
    return s[:64]


def mint_stem_token():
    """A capability to read the audio, for someone who has already logged in.

    Caddy has authenticated every request that reaches this service, so there
    is nobody to identify and nothing to encode: the token says only "issued,
    and good until". It grants exactly the authority the logged-in user
    already has, which is why it can be handed to a cache and a Worker that
    know nothing about passwords.
    """
    try:
        with open(TOKEN_KEY_PATH, encoding='utf-8') as f:
            key = f.read().strip()
    except OSError:
        return None, 0
    if not key:
        return None, 0
    exp = int(time.time()) + TOKEN_TTL

    msg = f'v1.{exp}'
    sig = base64.urlsafe_b64encode(
        hmac.new(key.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode().rstrip('=')
    return f'{msg}.{sig}', exp


class Handler(BaseHTTPRequestHandler):
    queue_path = None

    def _json(self, code, payload, cookie=None):
        """Write a JSON response, optionally with a Set-Cookie header.

        The cookie goes out HERE, after send_response has written the status
        line. A header sent before that lands in front of "HTTP/1.0 200 OK"
        in the output and the whole response stops being valid HTTP -- which
        is what made signup and login fail in every browser with "could not
        reach the server"."""
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def _cookie(self, name):
        """One cookie's value, or None. The header is a single line of
        name=value pairs; we only ever read our own, so a full parser is not
        worth it."""
        raw = self.headers.get('Cookie')
        if not raw:
            return None
        for part in raw.split(';'):
            k, _, v = part.strip().partition('=')
            if k == name:
                return v
        return None

    def _session_cookie(self, user, epoch=0):
        """The Set-Cookie VALUE for a login, to hand to _json. The epoch is
        the account's session counter -- minting with a stale one would lock
        the caller out of their own fresh password change."""
        bits = [f'beatz_session={make_session(user, epoch)}', 'Path=/',
                'HttpOnly', 'SameSite=Lax', f'Max-Age={SESSION_TTL}']
        if not DEV:
            bits.append('Secure')
        return '; '.join(bits)

    def _expired_session_cookie(self):
        """The Set-Cookie VALUE that clears the cookie."""
        bits = ['beatz_session=', 'Path=/', 'HttpOnly', 'SameSite=Lax',
                'Max-Age=0']
        if not DEV:
            bits.append('Secure')
        return '; '.join(bits)

    def _client_ip(self):
        """The real client's address, behind Caddy.

        reverse_proxy APPENDS the immediate peer's address to
        X-Forwarded-For, so the LAST entry is the one Caddy wrote; anything
        before it came from the browser and is not trustworthy. Without the
        header (a direct call) the socket peer is right. Keying the auth
        counter on client_address alone means every request arrives as
        127.0.0.1 -- one shared budget for the whole site."""
        xff = self.headers.get('X-Forwarded-For')
        if xff:
            last = xff.split(',')[-1].strip()
            if last:
                return last
        return self.client_address[0]

    def _who(self):
        """(login, role) for this request; role is 'admin' or 'viewer'.

        Three cases, decided deliberately:

        - X-Beatz-User present: it came through Caddy, which wrote the header
          itself after checking the password. Admin iff the login is in
          admins().
        - Header absent AND no X-Forwarded-For: a direct call to 127.0.0.1
          from the box itself -- the `curl` that seeded Karan's playlists and
          clips on 22 Sep. Anyone who can run that already has a shell on the
          box and could edit the JSON files directly, so there is nothing to
          protect by refusing them. Trusted, as it always has been.
        - Header absent BUT X-Forwarded-For present: it came through Caddy
          (reverse_proxy always sets X-Forwarded-For, overwriting any the
          browser sent) and yet Caddy named nobody -- the Caddyfile edit is
          missing or was rolled back. Fail closed: viewer. Otherwise a
          rolled-back Caddyfile would quietly make every tester an admin.

        The header is only trustworthy while Caddy is setting it. Without the
        header_up line Caddy passes a browser's own X-Beatz-User straight
        through (tested 22 Sep), so this service must never run behind a
        Caddyfile that lacks the edit: Caddy edit first, then this file; undo
        in the reverse order.

        The laptop's watcher never appears here at all: it works over SSH on
        the queue files, not through this service.
        """
        # A session cookie wins over the Caddy header: a real account is a
        # stronger statement of who this is than a shared basic-auth login.
        # It is read in every mode -- --dev included, where it is the only
        # way in.
        sess_user, sess_epoch = read_session(self._cookie('beatz_session'))
        if sess_user:
            acct = accounts().get(sess_user)
            # The epoch must match the account's current one: a password
            # change or reset bumps it, and every cookie minted before then
            # fails here -- a v1 cookie reads as epoch 0, which every account
            # is at until its first change.
            if acct and int(acct.get('sess') or 0) == int(sess_epoch or 0):
                return sess_user, (acct.get('role') if acct.get('role') in ROLES else 'editor')
            # A cookie for an account that has since been deleted -- or whose
            # password changed elsewhere: treat it as no login at all rather
            # than falling through to the header, which would silently
            # promote it to a Caddy login.
            return None, 'viewer'
        # In --dev there is no Caddy, so the header is ignored entirely --
        # trusting it there would let anyone on the LAN claim to be admin.
        if DEV:
            return None, 'viewer'
        user = (self.headers.get('X-Beatz-User') or '').strip()
        # A name that is not a login name is not a name. With basic_auth gone
        # from /api/*, Caddy still sends its header_up line UNRESOLVED -- the
        # literal "{http.auth.user.id}" -- which is truthy, and would otherwise
        # read as a signed-in viewer: anyone on the internet could have minted
        # a library token and filed requests. Reject the shape, not the string.
        if not valid_login(user):
            user = ''
        if not user:
            # No name at all. This used to trust a bare call from the box as an
            # admin, on the grounds that only the box can reach 127.0.0.1:8931
            # -- but with the site open, "no name" is also exactly what a
            # stripped proxy request looks like, so it fails closed. A local
            # caller who needs a role can send X-Beatz-User itself.
            return None, 'viewer'
        return user, (role_of(user) or 'viewer')

    def _pending(self):
        """Requests still waiting, NOT the size of the queue file.

        requests.jsonl is append-only and never trimmed, so counting its lines
        meant every song ever asked for counted against MAX_PENDING - the queue
        would have wedged shut at 50 requests forever, refusing everyone with
        "queue is full". Ids the watcher has finished live in done.txt."""
        done = self._done_ids()
        return sum(1 for e in self._queue_entries() if e.get('id') not in done)

    def _done_ids(self):
        """Ids the watcher has finished. Separate from results.jsonl: done.txt
        goes back to the first request, results.jsonl only to the day it was
        added, so anything processed before then is recorded HERE and nowhere
        else."""
        path = os.path.join(os.path.dirname(self.queue_path), 'done.txt')
        try:
            with open(path, encoding='utf-8') as f:
                return {l.strip() for l in f if l.strip()}
        except OSError:
            return set()

    def _queue_entries(self):
        if not os.path.exists(self.queue_path):
            return []
        out = []
        with open(self.queue_path, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        return out

    def _results(self):
        """Outcomes written back by watch-requests.py on the laptop. Last line
        for an id wins, so a retry overwrites an earlier failure."""
        path = os.path.join(os.path.dirname(self.queue_path), 'results.jsonl')
        out = {}
        if not os.path.exists(path):
            return out
        with open(path, encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('id'):
                    out[r['id']] = r
        return out

    def _read_json(self, limit):
        """The request body as a dict, or (None, True) once an error has been
        sent. It used to return self._json(...) as the error -- which is None,
        so `if err is not None` never fired: a bad body got its 400 and then
        the handler carried on with data=None and died on data.get(), and a
        JSON list or null got no response at all. Found 22 Sep testing
        /api/clips."""
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            self._json(400, {'error': 'bad length'})
            return None, True
        if length <= 0 or length > limit:
            self._json(413, {'error': 'body too large'})
            return None, True
        try:
            data = json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception:
            self._json(400, {'error': 'bad json'})
            return None, True
        if not isinstance(data, dict):
            self._json(400, {'error': 'body must be an object'})
            return None, True
        return data, None

    # ---- shared playlists --------------------------------------------
    # Playlists lived in each device's localStorage, so the person running the
    # night could build a set and nobody else could see it. One shared file,
    # because that is what a shared set means -- there are no accounts here and
    # inventing them to scope playlists per person would be a bigger change
    # than the feature.
    def _playlists_path(self):
        return os.path.join(os.path.dirname(self.queue_path), 'playlists.json')

    def _read_playlists(self):
        """(shared, per-user, shares, links, rev). A file written before
        per-user playlists or sharing existed has no such keys; each reads as
        {} and is only given one when something is next written."""
        try:
            with open(self._playlists_path(), encoding='utf-8') as f:
                d = json.load(f)
            up = d.get('userPlaylists')
            sh = d.get('shares')
            lk = d.get('shareLinks')
            return (d.get('playlists', {}), (up if isinstance(up, dict) else {}),
                    (sh if isinstance(sh, dict) else {}),
                    (lk if isinstance(lk, dict) else {}), int(d.get('rev', 0)))
        except Exception:
            return {}, {}, {}, {}, 0

    def _write_playlists(self, shared, user_pl, shares, links, rev):
        """The ONE writer for playlists.json. It used to be a dict literal
        inside post_playlists, which silently dropped any key it did not know
        about -- adding `shares` to the file would have been undone by the next
        ordinary save, and every grant with it."""
        tmp = self._playlists_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'playlists': shared, 'userPlaylists': user_pl,
                       'shares': shares, 'shareLinks': links, 'rev': rev},
                      f, ensure_ascii=False)
        os.replace(tmp, self._playlists_path())     # atomic: no half-written file

    def _playlist_payload(self, shared, user_pl, shares, links, rev, user, role):
        """What GET returns, what every 200 returns, and (with `error`) what a
        409 returns -- so a stale client reconciles from exactly the state it
        would have got from a fresh load. Only the caller's OWN shares and
        links are in here: nobody sees who else has access to anything.
        `role` is the caller's: an admin also manages the house shares and
        links (owner '@shared'), which is why it is passed in rather than
        re-derived -- role_of() does not know about session accounts."""
        meta, shadowed = visible_shares(user_pl, shared, shares, user)
        mine = dict(user_pl.get(user, {}) if user else {})
        for name, m in meta.items():
            if m['owner'] == SHARED_OWNER:
                mine[name] = shared.get(name, [])
            else:
                mine[name] = (user_pl.get(m['owner']) or {}).get(name, [])
        my_shares = owned_shares(shares, user)
        if role == 'admin':
            # The house shares are managed by ANY admin, so every admin sees
            # them all in their panel and can remove a person or revoke a link.
            for name, people in owned_shares(shares, SHARED_OWNER).items():
                my_shares.setdefault(name, {}).update(people)
        my_links = {t: {'name': r.get('name'), 'role': r.get('role'),
                        'created': r.get('created')}
                    for t, r in links.items()
                    if isinstance(r, dict)
                    and (r.get('owner') == user
                         or (role == 'admin' and r.get('owner') == SHARED_OWNER))}
        return {'ok': True, 'playlists': shared, 'mine': mine,
                'sharedMeta': meta, 'shadowed': shadowed,
                'myShares': my_shares, 'myLinks': my_links,
                'rev': rev}

    def _share_target(self, data, key, user, role):
        """(scope, owner, denial) for a preset or clip write.

        Resolves the caller's own bucket vs the shared set vs a grant on
        someone else's playlist, so both handlers agree. `denial` is a
        (code, error) pair when the write may not proceed at all."""
        scope = data.get('scope') or 'shared'
        owner = (data.get('owner') or '').strip()
        if scope == SHARE_SCOPE:
            if not valid_owner(owner):
                return scope, owner, (400, 'owner is required')
            with PLAYLISTS_LOCK:
                shared, user_pl, shares, _, _ = self._read_playlists()
                name = key_playlist(key)
                if owner == SHARED_OWNER:
                    exists = name in shared
                else:
                    exists = name in (user_pl.get(owner) or {})
                ok = (share_role(shares, user, owner, name) == 'edit'
                      and exists)
            return scope, owner, None if ok else (403, 'read-only')
        return scope, owner, scope_allowed(scope, user, role, None)

    def get_playlists(self):
        shared, user_pl, shares, links, rev = self._read_playlists()
        # The caller only ever sees their own bucket and what has been shared
        # with them, never anyone else's. The shared set is returned to
        # everyone, since that is what "shared" means.
        user, role = self._who()
        return self._json(200, self._playlist_payload(
            shared, user_pl, shares, links, rev, user, role))

    def post_playlists(self):
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        incoming = data.get('playlists')
        if not isinstance(incoming, dict):
            return self._json(400, {'error': 'playlists must be an object'})
        if len(incoming) > 100:
            return self._json(400, {'error': 'too many playlists'})
        clean = {}
        for name, dirs in incoming.items():
            if not isinstance(name, str) or not isinstance(dirs, list):
                continue
            name = name.strip()[:60]
            if not name:
                continue
            # Directory names only: these are looked up against the stems tree,
            # so anything with a slash or traversal in it has no business here.
            clean[name] = [d for d in dirs
                           if isinstance(d, str) and d and '/' not in d
                           and '\\' not in d and '..' not in d][:500]

        # Which set this write is for. "shared" is the set everyone sees and
        # only an admin may change; "user" is the caller's own bucket; "share"
        # is a per-playlist delta into SOMEONE ELSE's bucket, for a login the
        # owner gave an edit link to. Defaulting to "shared" keeps an old
        # client (which sends no scope) behaving exactly as before.
        scope = data.get('scope') or 'shared'
        owner = (data.get('owner') or '').strip()
        user, role = self._who()
        if scope not in ('shared', 'user', SHARE_SCOPE):
            return self._json(400, {'error': 'scope must be shared, user or share'})

        with PLAYLISTS_LOCK:
            shared, user_pl, shares, links, rev = self._read_playlists()
            if scope == SHARE_SCOPE:
                # One owner per write, and every name in it must be one they
                # gave the caller edit on. Only the names actually sent are
                # touched: a collaborator's delta can change a playlist but
                # never delete one. A sentinel owner resolves to the shared
                # set itself -- never a userPlaylists['@shared'] bucket.
                if not valid_owner(owner):
                    return self._json(400, {'error': 'owner is required'})
                bucket = shared if owner == SHARED_OWNER else (user_pl.get(owner) or {})
                for name in clean:
                    if name not in bucket:
                        return self._json(404, {'error': 'no such playlist'})
                    if share_role(shares, user, owner, name) != 'edit':
                        return self._json(403, {'error': 'read-only', 'role': role})
            else:
                denied = scope_allowed(scope, user, role, None)
                if denied:
                    return self._json(denied[0], {'error': denied[1], 'role': role})

            # Last-writer-wins would silently bin a playlist someone else just
            # made from another phone. The client sends the rev it started
            # from; a stale one gets the current state back and re-sends on top.
            sent = data.get('rev')
            if sent is not None:
                try:
                    stale = int(sent) != rev
                except (TypeError, ValueError):
                    return self._json(400, {'error': 'bad rev'})
                if stale:
                    body = self._playlist_payload(
                        shared, user_pl, shares, links, rev, user, role)
                    body.pop('ok', None)
                    body['error'] = 'stale'
                    return self._json(409, body)

            if scope == 'shared':
                shared = clean
                # The house set obeys the same rule as a personal one: a
                # deleted playlist takes its grants and links with it.
                prune_shares_for(shares, links, SHARED_OWNER, clean)
            elif scope == 'user':
                user_pl[user] = clean
                prune_shares_for(shares, links, user, clean)
            else:
                if owner == SHARED_OWNER:
                    shared.update(clean)
                else:
                    user_pl.setdefault(owner, {}).update(clean)
            rev += 1
            self._write_playlists(shared, user_pl, shares, links, rev)
            return self._json(200, self._playlist_payload(
                shared, user_pl, shares, links, rev, user, role))

    # ---- saved song setups -------------------------------------------
    # "Save Setup" lived in each browser's localStorage, so a mix saved on a
    # laptop was missing on the NUC driving the speakers. One shared file, like
    # playlists. Unlike playlists, a write carries ONE setup rather than the
    # whole map: two people saving different songs at once is the normal case
    # here, and neither should need to know about the other's.
    def _presets_path(self):
        return os.path.join(os.path.dirname(self.queue_path), 'presets.json')

    def _read_presets(self):
        """(shared, per-user). The file has always been a flat map of
        "<playlist>::<song>" -> setup, and stays that way: the per-user setups
        live under a single reserved key, so an old file reads correctly and a
        new one is still readable by anything that only knows the flat shape.
        The reserved key is not a valid preset key (it has no "::"), so it can
        never collide with a real one."""
        try:
            with open(self._presets_path(), encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            return {}, {}
        if not isinstance(d, dict):
            return {}, {}
        up = d.pop(USER_PRESETS_KEY, None)
        return d, (up if isinstance(up, dict) else {})

    def get_presets(self):
        shared, user_pr = self._read_presets()
        user, _ = self._who()
        own = user_pr.get(user, {}) if user else {}
        with PLAYLISTS_LOCK:
            shared_pl, user_pl, shares, _, _ = self._read_playlists()
        # A collaborator sees the owner's mixes for the playlists shared with
        # them, under the same bare keys as their own -- the client never has
        # to know who owns a playlist. Their own entry wins a clash.
        mine = shared_entries(user_pr, shared, user_pl, shared_pl, shares, user) if user else {}
        mine.update(own)
        return self._json(200, {'ok': True, 'presets': shared, 'mine': mine})

    def post_presets(self):
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        key = data.get('key')
        # "<playlist or all>::<song dir>", as the player builds it.
        # Only the song half is checked for path characters: it names a stems
        # directory. The playlist half is a name someone typed ("80s/90s").
        song_dir = key.rsplit('::', 1)[-1] if isinstance(key, str) else ''
        if (not isinstance(key, str) or '::' not in key or len(key) > 200 or not song_dir
                or '/' in song_dir or '\\' in song_dir or '..' in song_dir):
            return self._json(400, {'error': 'bad key'})
        setup = data.get('setup')
        clean = None
        if setup is not None:
            if not isinstance(setup, dict):
                return self._json(400, {'error': 'setup must be an object'})

            def num(v, lo, hi, default):
                return min(hi, max(lo, v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else default
            vols = setup.get('volumes') if isinstance(setup.get('volumes'), dict) else {}
            clean = {
                'position': num(setup.get('position'), 0, 1, 0),
                'volumes': {s: int(num(vols.get(s), 0, 100, 80))
                            for s in ('vocals', 'drums', 'bass', 'other') if s in vols},
                'preset': str(setup.get('preset') or '')[:20],
                'tempo': num(setup.get('tempo'), 0.25, 2, 1),
                'key': round(num(setup.get('key'), -12, 12, 0) * 2) / 2,   # half-semitone steps
                'tag': str(setup.get('tag') or '')[:40],
                'saved': int(time.time() * 1000),
            }
        # Which set this write is for, exactly as for playlists: "shared" is
        # the set everyone sees (admin only), "user" is the caller's own, and
        # "share" is a grant on someone else's playlist.
        user, role = self._who()
        scope, owner, denied = self._share_target(data, key, user, role)
        if denied:
            return self._json(denied[0], {'error': denied[1], 'role': role})

        # Read-modify-write under a lock: the server is threaded, and two saves
        # landing together would otherwise each write a map missing the other.
        with PRESETS_LOCK:
            shared, user_pr = self._read_presets()
            bucket_user = owner if scope == SHARE_SCOPE else user
            target = shared if (scope == 'shared' or owner == SHARED_OWNER) \
                else user_pr.setdefault(bucket_user, {})
            if clean is None:
                target.pop(key, None)
            else:
                if key not in target and len(target) >= 5000:
                    return self._json(400, {'error': 'too many saved setups'})
                target[key] = clean
            out = dict(shared)
            if user_pr:
                out[USER_PRESETS_KEY] = user_pr
            tmp = self._presets_path() + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False)
            os.replace(tmp, self._presets_path())
        return self._json(200, {'ok': True, 'setup': clean})

    # ---- playlist clips ----------------------------------------------
    # A start and an end for one song IN ONE PLAYLIST, so a set plays like a
    # DJ's: Bheegi Bheegi 0:25-3:30, fade, next song (asked for 22 Sep, for
    # the 25 Sep night). Deliberately not part of a saved setup: a setup
    # belongs to the song wherever it is played (Iti, 14 Sep), and a song
    # trimmed for one set must stay full length in every other. Same shape as
    # presets otherwise -- one write carries one clip, for the same reason.
    def _clips_path(self):
        return os.path.join(os.path.dirname(self.queue_path), 'clips.json')

    def _read_clips(self):
        """(shared, per-user), same flat-file-with-a-reserved-key shape as
        presets."""
        try:
            with open(self._clips_path(), encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            return {}, {}
        if not isinstance(d, dict):
            return {}, {}
        up = d.pop(USER_CLIPS_KEY, None)
        return d, (up if isinstance(up, dict) else {})

    def get_clips(self):
        shared, user_cl = self._read_clips()
        user, _ = self._who()
        own = user_cl.get(user, {}) if user else {}
        with PLAYLISTS_LOCK:
            shared_pl, user_pl, shares, _, _ = self._read_playlists()
        # Same merge as presets: the owner's clips for a playlist shared with
        # the caller arrive under the same bare keys, own entry winning.
        mine = shared_entries(user_cl, shared, user_pl, shared_pl, shares, user) if user else {}
        mine.update(own)
        return self._json(200, {'ok': True, 'clips': shared, 'mine': mine})

    def post_clips(self):
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        key = data.get('key')
        # "<playlist>::<song dir>". Checked exactly as a preset key is: the
        # song half names a stems directory, so no path characters; the
        # playlist half is a name someone typed and may hold a slash
        # ("80s/90s") -- post_playlists allows that, so refusing it here would
        # make that playlist's clips unsaveable.
        playlist, _, song_dir = key.rpartition('::') if isinstance(key, str) else ('', '', '')
        if (not isinstance(key, str) or not playlist.strip() or len(playlist) > 60
                or len(key) > 200 or not song_dir
                or '/' in song_dir or '\\' in song_dir or '..' in song_dir):
            return self._json(400, {'error': 'bad key'})
        clip = data.get('clip')
        clean = None
        if clip is not None:
            if not isinstance(clip, dict):
                return self._json(400, {'error': 'clip must be an object'})

            def secs(v):
                # Seconds into the song, to a tenth: finer than anyone hears,
                # and the file stays readable. Six hours is far past any song
                # in the library; anything outside it is not a timing.
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
                    return None
                return round(float(min(21600, max(0, v))), 1)
            start = secs(clip.get('start'))
            if start is None:
                start = 0.0
            end = None
            if clip.get('end') is not None:
                end = secs(clip.get('end'))
                # An end at or before the start is a clip of nothing. Refuse
                # it rather than store it: stored, the player would skip the
                # song the moment it started, which is a harder fault to find
                # at a gig than a refused save.
                if end is None or end <= start:
                    return self._json(400, {'error': 'end must come after start'})
            clean = {'start': start, 'end': end}
        # Which set this write is for, exactly as for playlists and presets.
        user, role = self._who()
        scope, owner, denied = self._share_target(data, key, user, role)
        if denied:
            return self._json(denied[0], {'error': denied[1], 'role': role})

        # Read-modify-write under a lock, as for presets: two people trimming
        # different songs at once must not each write a map missing the other.
        with CLIPS_LOCK:
            shared, user_cl = self._read_clips()
            bucket_user = owner if scope == SHARE_SCOPE else user
            target = shared if (scope == 'shared' or owner == SHARED_OWNER) \
                else user_cl.setdefault(bucket_user, {})
            if clean is None:
                target.pop(key, None)
            else:
                if key not in target and len(target) >= 5000:
                    return self._json(400, {'error': 'too many clips'})
                target[key] = clean
            out = dict(shared)
            if user_cl:
                out[USER_CLIPS_KEY] = user_cl
            tmp = self._clips_path() + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False)
            os.replace(tmp, self._clips_path())     # atomic: no half-written file
        return self._json(200, {'ok': True, 'clip': clean})

    # ---- live lyrics ---------------------------------------------------
    def _live_path(self):
        return os.path.join(os.path.dirname(self.queue_path), 'live.json')

    def _live_load(self):
        """(sessions, codes) -- expired sessions dropped, codes kept.

        `codes` maps a login to the code it always gets, so ONE link can be
        sent once and used all evening: it is live while the host is sharing,
        and answers "the host has stopped sharing" when they are not, instead
        of a different link every time the button is pressed. Kept in a file
        rather than memory so a restart mid-set does not orphan a link somebody
        is already following. Callers hold LIVE_LOCK."""
        try:
            with open(self._live_path(), encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            return {}, {}
        if not isinstance(d, dict):
            return {}, {}
        now = time.time()
        if 'sessions' not in d:                 # the shape from before codes
            sessions = {c: s for c, s in d.items()
                        if isinstance(s, dict) and 'user' in s}
            codes = {}
            for c, s in sessions.items():
                if s.get('user'):
                    codes.setdefault(s['user'], c)
        else:
            sessions = d.get('sessions') if isinstance(d.get('sessions'), dict) else {}
            codes = d.get('codes') if isinstance(d.get('codes'), dict) else {}
        sessions = {c: s for c, s in sessions.items()
                    if isinstance(s, dict) and now - float(s.get('updated') or 0) < LIVE_TTL}
        return sessions, codes

    def _live_write(self, sessions, codes):
        tmp = self._live_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'sessions': sessions, 'codes': codes}, f, ensure_ascii=False)
        os.replace(tmp, self._live_path())      # atomic, like every other file

    def post_live(self):
        """The host's publish. One live session per login: the first publish
        makes the code, later ones carry it back."""
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        user, role = self._who()
        if role not in ('editor', 'admin'):
            return self._json(403, {'error': 'read-only', 'role': role})
        dirname = str(data.get('dir') or '')
        if not re.fullmatch(r'[A-Za-z0-9_]+', dirname):
            return self._json(400, {'error': 'bad song'})
        try:
            pos = max(0.0, min(21600.0, float(data.get('pos') or 0)))
            tempo = min(4.0, max(0.1, float(data.get('tempo') or 1)))
        except (TypeError, ValueError):
            return self._json(400, {'error': 'bad position'})
        want = str(data.get('code') or '').strip()
        with LIVE_LOCK:
            sessions, codes = self._live_load()
            # The caller's own code, always the same one: what they sent if it
            # is genuinely theirs, else whatever this login got last time, else
            # a fresh one.
            code = codes.get(user) or ''
            if want and want in codes.values() and sessions.get(want, {}).get('user') == user:
                code = want
            if not code or not valid_code(code):
                code = secrets.token_urlsafe(8)     # 11 chars: the whole secret
            codes[user] = code
            sessions = {c: s for c, s in sessions.items() if s.get('user') != user}
            sessions[code] = {'user': user, 'dir': dirname,
                              'title': str(data.get('title') or '')[:80],
                              'pos': round(pos, 2), 'playing': bool(data.get('playing')),
                              'tempo': round(tempo, 3), 'updated': time.time()}
            if len(sessions) > LIVE_MAX:
                for c, _s in sorted(sessions.items(),
                                    key=lambda kv: kv[1].get('updated') or 0)[:len(sessions) - LIVE_MAX]:
                    del sessions[c]
            self._live_write(sessions, codes)
        return self._json(200, {'ok': True, 'code': code})

    def post_live_stop(self):
        """Ends the SESSION, not the link: the code stays this login's, so the
        link somebody already has keeps working the next time they share."""
        user, _ = self._who()
        with LIVE_LOCK:
            sessions, codes = self._live_load()
            mine = [c for c, s in sessions.items() if s.get('user') == user]
            for c in mine:
                del sessions[c]
            if mine:
                self._live_write(sessions, codes)
        return self._json(200, {'ok': True})

    def get_live(self, code):
        """PUBLIC -- no login, no Caddy. The code is the credential. `age` is
        how old the snapshot is, in ms, so the follower can extrapolate without
        trusting its own clock against the server's."""
        with LIVE_LOCK:
            sessions, _codes = self._live_load()
            s = sessions.get(code)
        if not s:
            return self._json(404, {'ok': False, 'error': 'no such session'})
        return self._json(200, {
            'ok': True, 'dir': s.get('dir'), 'title': s.get('title'),
            'pos': s.get('pos'), 'playing': bool(s.get('playing')),
            'tempo': s.get('tempo'),
            'age': int(max(0.0, time.time() - float(s.get('updated') or 0)) * 1000),
        })

    def get_live_lyrics(self, code):
        """PUBLIC: this session's song lyrics and nothing else. Serving them
        here rather than opening /stems/* keeps the rest of the library behind
        the password: only the one song being broadcast is readable, and only
        by a holder of the code."""
        with LIVE_LOCK:
            sessions, _codes = self._live_load()
            s = sessions.get(code)
        if not s:
            return self._json(404, {'error': 'no such session'})
        dirname = str(s.get('dir') or '')
        if not re.fullmatch(r'[A-Za-z0-9_]+', dirname):
            return self._json(404, {'error': 'no lyrics for this song'})
        try:
            with open(os.path.join(WEB_DIR, 'stems', dirname, 'lyrics_timed.json'),
                      encoding='utf-8') as f:
                return self._json(200, json.load(f))
        except Exception:
            return self._json(404, {'error': 'no lyrics for this song'})

    # ---- share links --------------------------------------------------
    # Sharing is by link rather than by typing somebody's login: the owner
    # makes a view link or an edit link and sends it however they like, and
    # whoever opens it CLAIMS it -- which needs a login, so a link is an
    # invitation and never an anonymous grant. The token is the whole
    # credential, so it is long and random; revoking a link stops new claims,
    # while people who already claimed keep their grant until the owner removes
    # them from the share panel.
    def post_share_links(self):
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        user, role = self._who()
        if not user:
            return self._json(400, {'error': 'login required'})
        with PLAYLISTS_LOCK:
            shared, user_pl, shares, links, rev = self._read_playlists()
            if data.get('revoke'):
                token = str(data.get('token') or '').strip()
                rec = links.get(token) if token else None
                # A house link is any admin's to revoke; a personal one only
                # its creator's.
                mine_link = isinstance(rec, dict) and (
                    rec.get('owner') == user
                    or (role == 'admin' and rec.get('owner') == SHARED_OWNER))
                if not mine_link:
                    return self._json(404, {'error': 'no such link'})
                del links[token]
                token = None
            else:
                name = str(data.get('name') or '').strip()[:60]
                lrole = data.get('role')
                if lrole not in SHARE_ROLES:
                    return self._json(400, {'error': 'role must be view or edit'})
                # The house set first for an admin: that is the set their
                # screen shows, and the one they are looking at when they
                # press Share. An editor can only ever share their own bucket.
                if role == 'admin' and name in shared:
                    share_owner = SHARED_OWNER
                elif name in (user_pl.get(user) or {}):
                    share_owner = user
                else:
                    return self._json(404, {'error': 'no such playlist'})
                mine_links = [r for r in links.values()
                              if isinstance(r, dict)
                              and (r.get('owner') == user
                                   or (role == 'admin'
                                       and r.get('owner') == SHARED_OWNER))]
                if len(mine_links) >= MAX_SHARES_PER_PLAYLIST:
                    return self._json(400, {'error': 'too many share links'})
                token = secrets.token_urlsafe(12)
                links[token] = {'owner': share_owner, 'name': name, 'role': lrole,
                                'created': int(time.time())}
            rev += 1
            self._write_playlists(shared, user_pl, shares, links, rev)
            body = self._playlist_payload(shared, user_pl, shares, links, rev, user, role)
            body['token'] = token        # the one just made, or None on a revoke
            return self._json(200, body)

    def post_share_claim(self):
        """The recipient's half: opening a link. Idempotent, and it never
        downgrades -- someone with edit who opens a view link keeps edit --
        so a second claim costs no rev."""
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        user, role = self._who()
        if not user:
            return self._json(400, {'error': 'login required'})
        token = str(data.get('token') or '').strip()
        with PLAYLISTS_LOCK:
            shared, user_pl, shares, links, rev = self._read_playlists()
            rec = links.get(token) if token else None
            if not isinstance(rec, dict):
                return self._json(404, {'error': 'that link is not valid'})
            owner, name, lrole = rec.get('owner'), rec.get('name'), rec.get('role')
            if lrole not in SHARE_ROLES or not valid_owner(owner) or not isinstance(name, str):
                return self._json(404, {'error': 'that link is not valid'})
            if owner == SHARED_OWNER:
                exists = name in shared
            else:
                exists = name in (user_pl.get(owner) or {})
            if not exists:
                return self._json(404, {'error': 'that playlist no longer exists'})
            # An admin already has the house set in full; claiming a house
            # link would only move the playlist into their "Shared with me"
            # and hide their editing controls for it. Same answer as for
            # anyone following their own link.
            if owner == user or (owner == SHARED_OWNER and role == 'admin'):
                return self._json(400, {'error': 'that is your own playlist'})
            held = shares.setdefault(user, {}).setdefault(owner, {})
            want = 'edit' if 'edit' in (held.get(name), lrole) else 'view'
            if held.get(name) != want:
                total = sum(len(m) for m in shares.get(user, {}).values())
                if total >= MAX_SHARES_IN:
                    return self._json(400, {'error': 'too many shared playlists'})
                held[name] = want
                rev += 1
                self._write_playlists(shared, user_pl, shares, links, rev)
            body = self._playlist_payload(shared, user_pl, shares, links, rev, user, role)
            body['claimed'] = {'owner': owner, 'name': name, 'role': held.get(name)}
            return self._json(200, body)

    def post_shares(self):
        """The owner's grip on their own playlist: remove one person, or change
        their role. A recipient uses the same call to leave."""
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        user, role = self._who()
        if not user:
            return self._json(400, {'error': 'login required'})
        name = str(data.get('name') or '').strip()[:60]
        if not name:
            return self._json(400, {'error': 'playlist is required'})
        with PLAYLISTS_LOCK:
            shared, user_pl, shares, links, rev = self._read_playlists()
            if data.get('leave'):
                owner = str(data.get('owner') or '').strip()
                if not valid_owner(owner):
                    return self._json(400, {'error': 'owner is required'})
                held = (shares.get(user) or {}).get(owner)
                if isinstance(held, dict) and name in held:
                    del held[name]
                    if not held:
                        del shares[user][owner]
                    if not shares.get(user):
                        del shares[user]
                    rev += 1
                    self._write_playlists(shared, user_pl, shares, links, rev)
            else:
                # Which of the caller's maps this playlist is in. The house
                # set first for an admin: it is the set their screen shows,
                # and the only one their Share panel ever offers.
                if role == 'admin' and name in shared:
                    owner_key = SHARED_OWNER
                elif name in (user_pl.get(user) or {}):
                    owner_key = user
                else:
                    return self._json(404, {'error': 'no such playlist'})
                recipient = str(data.get('user') or '').strip()
                if not valid_login(recipient) or recipient == user:
                    return self._json(400, {'error': 'bad user name'})
                held = (shares.get(recipient) or {}).get(owner_key)
                grant = data.get('role')
                changed = False
                if grant in SHARE_ROLES:
                    if held is None:
                        held = shares.setdefault(recipient, {}).setdefault(owner_key, {})
                    changed = held.get(name) != grant
                    held[name] = grant
                elif isinstance(held, dict) and name in held:
                    del held[name]
                    changed = True
                    if not held:
                        del shares[recipient][owner_key]
                    if not shares.get(recipient):
                        del shares[recipient]
                if changed:
                    rev += 1
                    self._write_playlists(shared, user_pl, shares, links, rev)
            return self._json(200, self._playlist_payload(
                shared, user_pl, shares, links, rev, user, role))

    # ---- users -------------------------------------------------------
    # Who may log in and what they may do. The PASSWORD is not here: Caddy
    # owns it (bcrypt in the Caddyfile), and server/add-user.sh is what adds a
    # login there. This file only records the ROLE, so the service can decide
    # what a login may write without reimplementing password storage.
    def _read_users(self):
        try:
            with open(USERS_FILE, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            return {}
        return d.get('users') if isinstance(d.get('users'), dict) else {}

    def get_users(self):
        if self._who()[1] != 'admin':
            return self._json(403, {'error': 'read-only', 'role': self._who()[1]})
        known = self._read_users()
        # Every login the service knows about, whether it came from users.json
        # or the admins() rule, so the list is not missing the two accounts
        # that predate the file.
        out = {}
        for name in set(known) | admins():
            role = role_of(name)
            if role:
                out[name] = {'role': role,
                             'inFile': name in known}
        return self._json(200, {'ok': True, 'users': out})

    def post_users(self):
        if self._who()[1] != 'admin':
            return self._json(403, {'error': 'read-only', 'role': self._who()[1]})
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        name = (data.get('user') or '').strip()
        role = data.get('role')
        if not name or len(name) > 40 or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            return self._json(400, {'error': 'bad user name'})
        if role not in ROLES:
            return self._json(400, {'error': 'role must be one of ' + ', '.join(ROLES)})
        # Refuse to demote the last admin: with no admin left, nobody can
        # change the shared set or add users back, and the only way out is a
        # shell on the box.
        if role != 'admin':
            remaining = {n for n in set(self._read_users()) | admins()
                         if n != name and role_of(n) == 'admin'}
            if not remaining:
                return self._json(400, {'error': 'that would leave no admin'})
        # Read-modify-write the WHOLE file, keeping every other key it holds:
        # users.json also carries the accounts map, and writing a fresh
        # {"users": ...} over it deleted every signup on the site.
        with USERS_LOCK:
            d = _read_users_file()
            known = d.get('users') if isinstance(d.get('users'), dict) else {}
            if data.get('delete'):
                known.pop(name, None)
            else:
                known[name] = {'role': role}
            d['users'] = known
            _write_users(d)     # atomic, and 0600: it holds password hashes
        return self._json(200, {'ok': True, 'user': name, 'role': role,
                                'deleted': bool(data.get('delete'))})

    # ---- accounts: signup, login, logout, reset ----------------------
    # The only endpoints an unauthenticated caller can reach. Everything else
    # needs either a session cookie or a Caddy login. Since 1 Oct a signup
    # needs an INVITE CODE and an email (the reset channel), and the password
    # must pass valid_password().
    def _auth_body(self):
        """(user, password) from the request body, or (None, None) after
        having already sent an error.

        Login validates the SHAPE only, never the policy: a rule added today
        must not lock out a password that was legal yesterday."""
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return None, None
        user = (data.get('user') or '').strip()
        pw = data.get('password') or ''
        if not user or len(user) > 40 or not re.fullmatch(r'[A-Za-z0-9_.-]+', user):
            self._json(400, {'error': 'User name must be letters, digits, dot, dash or underscore.'})
            return None, None
        if not pw:
            self._json(400, {'error': 'Password is required.'})
            return None, None
        return user, pw

    def post_signup(self):
        ip = self._client_ip()
        if not auth_check(ip):
            return self._json(429, {'error': 'Too many attempts. Try again later.'})
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        user = (data.get('user') or '').strip()
        pw = data.get('password') or ''
        email = (data.get('email') or '').strip()
        invite = normalize_invite(data.get('invite'))
        if not user or len(user) > 40 or not re.fullmatch(r'[A-Za-z0-9_.-]+', user):
            return self._json(400, {'error': 'User name must be letters, digits, dot, dash or underscore.'})
        why = valid_password(user, pw)
        if why:
            return self._json(400, {'error': why})
        if not valid_email(email):
            return self._json(400, {'error': 'A valid email address is required — it is how a password reset would reach you.'})
        with USERS_LOCK:
            d = _read_users_file()
            accts = d.get(ACCOUNTS_KEY) if isinstance(d.get(ACCOUNTS_KEY), dict) else {}
            # A name already used by a Caddy login is refused too: otherwise a
            # signup could shadow `admin` and the two would disagree about who
            # that is.
            if user in accts or user in admins() or user in users():
                return self._json(409, {'error': 'That name is taken.'})
            # One email, one account: "forgot" resolves by name OR email, and
            # two accounts answering to one address would make that ambiguous.
            if email.lower() in [(r.get('email') or '').lower()
                                 for r in accts.values() if isinstance(r, dict)]:
                return self._json(409, {'error': 'That email is already on another account.'})
            invites = d.get('invites') if isinstance(d.get('invites'), dict) else {}
            rec = invites.get(invite) if invite else None
            left = rec.get('uses_left') if isinstance(rec, dict) else None
            if not isinstance(rec, dict) or (left is not None and left <= 0):
                auth_record(ip)     # guessing codes is the thing to throttle
                return self._json(403, {'error': 'That invite code is not valid.'})
            try:
                accts[user] = {'pw': hash_password(pw), 'role': 'editor',
                               'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                               'email': email, 'invite': invite}
            except ImportError:
                return self._json(500, {'error': 'Server is missing bcrypt; ask the admin to install it.'})
            if left is not None:
                rec['uses_left'] = left - 1
            rec.setdefault('used_by', []).append(user)
            d['invites'] = invites
            d[ACCOUNTS_KEY] = accts
            _write_users(d)
        cfg = mail_config()
        if cfg:
            # She gatekeeps signups; this is how she learns one happened
            # without opening the app. Best effort, like every mail.
            send_mail(cfg.get('notify') or '',
                      f'New Beatznbox account: {user}',
                      f'{user} created an account with the email {email} '
                      f'(invite {invite}).')
        return self._json(200, {'ok': True, 'user': user, 'role': 'editor'},
                          cookie=self._session_cookie(user, 0))

    def post_login(self):
        ip = self._client_ip()
        if not auth_check(ip):
            return self._json(429, {'error': 'Too many attempts. Try again later.'})
        user, pw = self._auth_body()
        if user is None:
            return
        acct = accounts().get(user)
        # One message for "no such user" and "wrong password": telling them
        # apart would let anyone enumerate the accounts.
        if not acct or not check_password(pw, acct.get('pw') or ''):
            auth_record(ip)
            return self._json(401, {'error': 'Wrong user name or password.'})
        role = acct.get('role') if acct.get('role') in ROLES else 'editor'
        return self._json(200, {'ok': True, 'user': user, 'role': role},
                          cookie=self._session_cookie(user, acct.get('sess') or 0))

    def post_logout(self):
        # Clears the browser's cookie. The token itself stays valid until it
        # expires -- unless the password changes or is reset, which bumps the
        # account's session epoch and outdates every cookie at once.
        return self._json(200, {'ok': True}, cookie=self._expired_session_cookie())

    def post_forgot(self):
        """Start a password reset. The reply is ALWAYS the same shape, whether
        the account exists, has an email, or neither -- the only thing it says
        is whether mail is set up at all, which is a fact about the site, not
        about any account."""
        ip = self._client_ip()
        if not forgot_check(ip):
            return self._json(429, {'error': 'Too many reset requests. Try again later.'})
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        who = str(data.get('user') or '').strip()
        cfg = mail_config()
        have_mail = bool(cfg and cfg.get('host'))
        out = {'ok': True, 'mail': have_mail}
        letter = None
        if who and have_mail:
            with USERS_LOCK:
                d = _read_users_file()
                accts = d.get(ACCOUNTS_KEY) if isinstance(d.get(ACCOUNTS_KEY), dict) else {}
                name = who if who in accts else None
                if name is None:
                    low = who.lower()
                    name = next((n for n, r in accts.items()
                                 if isinstance(r, dict)
                                 and (r.get('email') or '').lower() == low), None)
                rec = accts.get(name) if name else None
                email = (rec or {}).get('email') or ''
                now = time.time()
                prev = rec.get('reset') if isinstance(rec, dict) else None
                floor_ok = not isinstance(prev, dict) or \
                    now - float(prev.get('last_sent') or 0) >= 60
                if isinstance(rec, dict) and email and floor_ok:
                    token = secrets.token_urlsafe(32)
                    # Only the HASH is stored: users.json leaking must not
                    # mint resets. One live token per account -- a resend
                    # replaces the old link, and so does using it.
                    rec['reset'] = {'h': hashlib.sha256(token.encode()).hexdigest(),
                                    'exp': int(now) + RESET_TTL, 'last_sent': now}
                    accts[name] = rec
                    d[ACCOUNTS_KEY] = accts
                    _write_users(d)
                    base = (cfg.get('base') or 'https://beatznbox.wesimplyhome.com').rstrip('/')
                    link = f'{base}/#reset={token}'
                    letter = (email, 'Reset your Beatznbox password',
                              'Someone asked to reset the password for the '
                              f'Beatznbox account "{name}".\n\n'
                              f'Open this link to choose a new one:\n\n{link}\n\n'
                              f'The link works for {RESET_TTL // 60} minutes and only once.\n'
                              'If this was not you, nothing needs doing — your '
                              'password still works.\n')
        forgot_record(ip)       # every call counts, success or not
        if letter:
            send_mail(*letter)  # outside the lock: SMTP must not block writers
        return self._json(200, out)

    def post_reset(self):
        """Finish a reset: token in, new password out, and the caller is
        signed in on the spot (the reply carries a fresh cookie, so the
        password never makes a second trip through the login form)."""
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        token = str(data.get('token') or '').strip()
        pw = data.get('password') or ''
        if not token:
            return self._json(400, {'error': 'That reset link is no longer valid.'})
        digest = hashlib.sha256(token.encode()).hexdigest()
        user, epoch = None, 0
        with USERS_LOCK:
            d = _read_users_file()
            accts = d.get(ACCOUNTS_KEY) if isinstance(d.get(ACCOUNTS_KEY), dict) else {}
            now = time.time()
            for name, rec in accts.items():
                rr = rec.get('reset') if isinstance(rec, dict) else None
                if not isinstance(rr, dict):
                    continue
                if not hmac.compare_digest(str(rr.get('h') or ''), digest):
                    continue
                if float(rr.get('exp') or 0) < now:
                    break                     # found but expired: same answer
                why = valid_password(name, pw)
                if why:
                    # The token SURVIVES a policy rejection, so the person
                    # does not have to ask for a fresh link to try again.
                    return self._json(400, {'error': why})
                try:
                    rec['pw'] = hash_password(pw)
                except ImportError:
                    return self._json(500, {'error': 'Server is missing bcrypt; ask the admin to install it.'})
                rec['sess'] = int(rec.get('sess') or 0) + 1
                rec.pop('reset', None)
                accts[name] = rec
                d[ACCOUNTS_KEY] = accts
                _write_users(d)
                user, epoch = name, rec['sess']
                break
        if not user:
            return self._json(400, {'error': 'That reset link is no longer valid.'})
        return self._json(200, {'ok': True, 'user': user},
                          cookie=self._session_cookie(user, epoch))

    def post_email(self):
        """Set or change the account's email. The current password is
        required even though the session already proves the login: a long
        stale cookie must not be able to redirect where reset mail goes."""
        user, _ = self._who()
        acct = accounts().get(user) if user else None
        if not acct:
            return self._json(400, {'error': 'This login has no account to carry an email.'})
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        email = (data.get('email') or '').strip()
        current = data.get('current') or ''
        if not valid_email(email):
            return self._json(400, {'error': 'That does not look like an email address.'})
        if not check_password(current, acct.get('pw') or ''):
            return self._json(403, {'error': 'Current password is wrong.'})
        with USERS_LOCK:
            d = _read_users_file()
            accts = d.get(ACCOUNTS_KEY) if isinstance(d.get(ACCOUNTS_KEY), dict) else {}
            for other, r in accts.items():
                if other != user and isinstance(r, dict) \
                        and (r.get('email') or '').lower() == email.lower():
                    return self._json(409, {'error': 'That email is already on another account.'})
            rec = accts.get(user)
            if not isinstance(rec, dict):
                return self._json(400, {'error': 'This login has no account to carry an email.'})
            rec['email'] = email
            rec.pop('reset', None)      # a new address invalidates a pending reset
            accts[user] = rec
            d[ACCOUNTS_KEY] = accts
            _write_users(d)
        return self._json(200, {'ok': True, 'email': email})

    def post_password(self):
        """Change your own password, knowing the current one. The reply mints
        a cookie at the NEW epoch, so this device stays signed in while every
        other one is out."""
        user, _ = self._who()
        acct = accounts().get(user) if user else None
        if not acct:
            return self._json(400, {'error': 'This login has no account password to change.'})
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        current = data.get('current') or ''
        new = data.get('new') or ''
        if not check_password(current, acct.get('pw') or ''):
            return self._json(403, {'error': 'Current password is wrong.'})
        why = valid_password(user, new)
        if why:
            return self._json(400, {'error': why})
        with USERS_LOCK:
            d = _read_users_file()
            accts = d.get(ACCOUNTS_KEY) if isinstance(d.get(ACCOUNTS_KEY), dict) else {}
            rec = accts.get(user)
            if not isinstance(rec, dict):
                return self._json(400, {'error': 'This login has no account password to change.'})
            try:
                rec['pw'] = hash_password(new)
            except ImportError:
                return self._json(500, {'error': 'Server is missing bcrypt; ask the admin to install it.'})
            rec['sess'] = int(rec.get('sess') or 0) + 1
            rec.pop('reset', None)      # a changed password kills a pending reset
            accts[user] = rec
            d[ACCOUNTS_KEY] = accts
            _write_users(d)
            epoch = rec['sess']
        return self._json(200, {'ok': True}, cookie=self._session_cookie(user, epoch))

    def get_me(self):
        """Who the caller is, for the player to decide what to show. Distinct
        from /api/whoami, which predates accounts and is kept as it was."""
        user, role = self._who()
        acct = accounts().get(user) if user else None
        email = (acct or {}).get('email') or ''
        return self._json(200, {
            'ok': True,
            'user': user,
            'role': role,
            'account': bool(acct),
            'email': email,
            'has_email': bool(email),
            'canEditShared': role == 'admin',
            'canEditOwn': role in ('admin', 'editor'),
        })

    # ---- admin: who joined, and the invite codes ----------------------
    def get_accounts(self):
        """Every account, for the admin's Users list. This is how she sees
        who signed up -- the email notification is best effort."""
        if self._who()[1] != 'admin':
            return self._json(403, {'error': 'read-only'})
        accts = accounts()
        out = []
        for name in sorted(accts):
            r = accts.get(name) if isinstance(accts.get(name), dict) else {}
            out.append({'user': name, 'role': r.get('role') or 'editor',
                        'created': r.get('created') or '',
                        'email': r.get('email') or '',
                        'invite': r.get('invite') or ''})
        return self._json(200, {'ok': True, 'accounts': out})

    def _invites(self):
        d = _read_users_file()
        inv = d.get('invites') if isinstance(d.get('invites'), dict) else {}
        return [dict(r if isinstance(r, dict) else {}, code=c) for c, r in inv.items()]

    def get_invites(self):
        if self._who()[1] != 'admin':
            return self._json(403, {'error': 'read-only'})
        return self._json(200, {'ok': True, 'invites': self._invites()})

    def post_invites(self):
        """Create a code, or disable one. Codes are the public door now, so
        this stays with the admin alone."""
        if self._who()[1] != 'admin':
            return self._json(403, {'error': 'read-only'})
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        disable = normalize_invite(data.get('disable'))
        code = ''
        with USERS_LOCK:
            d = _read_users_file()
            inv = d.get('invites') if isinstance(d.get('invites'), dict) else {}
            if disable:
                if disable not in inv:
                    return self._json(404, {'error': 'no such invite code'})
                del inv[disable]
            else:
                uses = data.get('uses', 1)
                if uses is not None:
                    if not isinstance(uses, int) or isinstance(uses, bool) \
                            or not (1 <= uses <= 200):
                        return self._json(400, {'error': 'uses must be 1-200, or null for unlimited'})
                for _ in range(10):         # a generated collision is absurd; bounded anyway
                    code = new_invite_code()
                    if code not in inv:
                        break
                inv[code] = {'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                             'uses_left': uses,
                             'note': str(data.get('note') or '').strip()[:60],
                             'used_by': []}
            d['invites'] = inv
            _write_users(d)
        return self._json(200, {'ok': True, 'code': code or None,
                                'invites': self._invites()})

    # ---- static files, --dev only ------------------------------------
    # On the VPS Caddy serves the player and this service only ever sees
    # /api/*. In --dev there is no Caddy, so the service serves the player
    # too, and the whole app runs from one process on one port.
    def serve_static(self, path):
        root = os.path.realpath(WEB_DIR)
        rel = path.lstrip('/') or 'index.html'
        full = os.path.realpath(os.path.join(root, rel))
        # Refuse anything that escapes the web root, however it is spelled.
        if not (full == root or full.startswith(root + os.sep)):
            return self._json(404, {'error': 'not found'})
        if os.path.isdir(full):
            full = os.path.join(full, 'index.html')
        if not os.path.isfile(full):
            return self._json(404, {'error': 'not found'})
        ctype = {
            '.html': 'text/html; charset=utf-8',
            '.js': 'text/javascript; charset=utf-8',
            '.json': 'application/json',
            '.css': 'text/css; charset=utf-8',
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.svg': 'image/svg+xml',
            '.png': 'image/png',
            '.ico': 'image/x-icon',
        }.get(os.path.splitext(full)[1].lower(), 'application/octet-stream')
        try:
            with open(full, 'rb') as f:
                body = f.read()
        except OSError:
            return self._json(404, {'error': 'not found'})
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        # The page changes on every deploy; the audio does not. Same rule as
        # the Caddyfile, so a phone does not serve yesterday's index.html.
        if os.path.basename(full) in ('index.html', 'sw.js') or full.endswith('.json'):
            self.send_header('Cache-Control', 'no-cache, must-revalidate')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_POST(self):
        path = self.path.rstrip('/')
        # The refusal that matters is inside each handler, through
        # scope_allowed: the shared set is admin-only, a login may write its
        # own, and a share grant lets exactly one playlist be written by
        # whoever holds the link. A viewer's refused write still comes back
        # 403 read-only, which is what the player's fallbacks key on.
        if path == '/api/lyrics':
            return self.post_lyrics()
        if path == '/api/playlists':
            return self.post_playlists()
        if path == '/api/presets':
            return self.post_presets()
        if path == '/api/clips':
            return self.post_clips()
        if path == '/api/live':
            return self.post_live()
        if path == '/api/live/stop':
            return self.post_live_stop()
        if path == '/api/shares':
            return self.post_shares()
        if path == '/api/share-links':
            return self.post_share_links()
        if path == '/api/share-links/claim':
            return self.post_share_claim()
        if path == '/api/users':
            return self.post_users()
        if path == '/api/signup':
            return self.post_signup()
        if path == '/api/login':
            return self.post_login()
        if path == '/api/logout':
            return self.post_logout()
        if path == '/api/forgot':
            return self.post_forgot()
        if path == '/api/reset':
            return self.post_reset()
        if path == '/api/password':
            return self.post_password()
        if path == '/api/email':
            return self.post_email()
        if path == '/api/invites':
            return self.post_invites()
        if path == '/api/report':
            return self.post_report()
        if path != '/api/request':
            return self._json(404, {'error': 'not found'})
        if self._logged_in() is None:
            return
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        song = (data.get('song') or '').strip()[:MAX_FIELD]
        detail = (data.get('detail') or '').strip()[:MAX_FIELD]
        who = (data.get('who') or '').strip()[:40]
        if not song:
            return self._json(400, {'error': 'song is required'})
        name = slug(song)
        if not name:
            return self._json(400, {'error': 'song name has no usable characters'})
        if self._pending() >= MAX_PENDING:
            return self._json(429, {'error': 'queue is full'})

        # Already in the library: say so and do not queue it. Processing a song
        # we have costs ~10 minutes of separation and republishes the same file.
        existing = known_songs().get(norm(song))
        if existing:
            return self._json(409, {'error': f'"{existing}" is already in the list.',
                                    'duplicate': True, 'existing': existing})

        # Already asked for by someone else and not yet processed.
        for line in self._queue_entries():
            if norm(line.get('song')) == norm(song):
                return self._json(409, {
                    'error': f'Already requested by {line.get("who") or "someone"}.',
                    'duplicate': True, 'existing': line.get('song')})

        entry = {
            'id': f"{int(time.time())}-{name[:24]}",
            'name': name,
            # Kept verbatim for the YouTube and lyrics searches. The pipeline
            # passes these as arguments, never through a shell.
            'song': song,
            'detail': detail,
            'who': who,
            'requested': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'state': 'queued',
        }
        os.makedirs(os.path.dirname(self.queue_path), exist_ok=True)
        with open(self.queue_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())
        return self._json(200, {'ok': True, 'id': entry['id'], 'name': name})

    def _logged_in(self):
        """(user, role), or None after having refused an anonymous write.

        While the site sits behind Caddy's password every caller is already
        somebody. Open the site (30 Sep) and "anonymous" becomes the whole
        internet -- so the three endpoints whose output the laptop then ACTS
        on (it downloads a requested song, it files a report, it aligns pasted
        lyrics) ask for a login. Reading stays open, and so does the live
        lyrics page: that is the one thing a stranger is meant to reach."""
        user, role = self._who()
        if user or role == 'admin':     # role admin with no name = a local call
            return user, role
        self._json(403, {'error': 'login required'})
        return None

    def post_lyrics(self):
        """Words pasted in the player for a song LRCLIB does not carry.

        Written to a drop directory rather than the request queue: the watcher
        treats these differently — no download, no separation, just align the
        words against stems that already exist."""
        if self._logged_in() is None:
            return
        data, err = self._read_json(MAX_LYRICS)
        if err is not None:
            return
        name = slug((data.get('dir') or '').strip())
        text = (data.get('lyrics') or '').strip()
        if not name:
            return self._json(400, {'error': 'which song?'})
        if len([l for l in text.split('\n') if l.strip()]) < 4:
            # A stub that looks like success is the failure this whole library
            # keeps hitting — refuse it at the door.
            return self._json(400, {'error': 'needs at least 4 lines'})
        drop = os.path.join(os.path.dirname(self.queue_path), 'lyrics')
        os.makedirs(drop, exist_ok=True)
        with open(os.path.join(drop, name + '.txt'), 'w', encoding='utf-8') as f:
            f.write(text + '\n')
            f.flush()
            os.fsync(f.fileno())
        n = len([l for l in text.split('\n') if l.strip()])
        return self._json(200, {'ok': True, 'name': name, 'lines': n})

    def post_report(self):
        """Someone listening says this song is wrong.

        Until now the only detector for a bad song was Iti playing it and
        noticing -- which is how both of 2 Sep's mismatched songs were found,
        one of them graded "good" by every automatic check we have. The room
        hears these before any script does, so let the room say so.

        Appended, never rewritten: the same rule the request queue follows, so
        a half-finished write cannot lose what came before it.
        """
        if self._logged_in() is None:
            return
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        name = slug((data.get('dir') or '').strip())
        reason = (data.get('reason') or '').strip()
        if not name:
            return self._json(400, {'error': 'which song?'})
        if reason not in REPORT_REASONS:
            return self._json(400, {'error': 'unknown reason'})
        rec = {
            'id': f"r{int(time.time() * 1000)}",
            'dir': name,
            'song': (data.get('song') or '')[:MAX_FIELD],
            'reason': reason,
            'note': (data.get('note') or '')[:MAX_NOTE],
            'who': (data.get('who') or '')[:MAX_FIELD],
            'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        path = os.path.join(os.path.dirname(self.queue_path), 'reports.jsonl')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())
        return self._json(200, {'ok': True, 'id': rec['id']})

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        path = u.path.rstrip('/')
        if path == '/api/health':
            return self._json(200, {'ok': True, 'pending': self._pending()})
        if path == '/api/whoami':
            # The player asks once per load to decide whether to show the
            # playlist and clip editing controls. Presentation only: the
            # refusal that matters is in do_POST.
            user, role = self._who()
            return self._json(200, {'user': user, 'role': role,
                                    'canEditShared': role == 'admin',
                                    'canEditOwn': role in ('admin', 'editor'),
                                    'local': user is None and role == 'admin'})
        if path == '/api/playlists':
            return self.get_playlists()
        if path == '/api/presets':
            return self.get_presets()
        if path == '/api/clips':
            return self.get_clips()
        if path == '/api/users':
            return self.get_users()
        if path == '/api/accounts':
            return self.get_accounts()
        if path == '/api/invites':
            return self.get_invites()
        if path == '/api/me':
            return self.get_me()
        if path.startswith('/api/live/'):
            # PUBLIC: /api/live/<code> and /api/live/<code>/lyrics. No login
            # and no X-Beatz-User check -- the code in the URL is the whole
            # credential, exactly like a stem token.
            rest = path[len('/api/live/'):].strip('/')
            if rest.endswith('/lyrics'):
                return self.get_live_lyrics(rest[:-len('/lyrics')].strip('/'))
            return self.get_live(rest)
        if path == '/api/stem-token':
            # A LOGIN is required to mint one. The token unlocks the whole
            # library from the edge, so the moment the site is reachable
            # without the Caddy password this line is what keeps the audio
            # private. Caddy logins still pass it (they arrive with a name);
            # a call from the box itself (role admin, no name) does too.
            user, role = self._who()
            if not user and role != 'admin':
                return self._json(403, {'error': 'login required'})
            token, exp = mint_stem_token()
            if not token:
                # No key on the box means the edge is not set up. Say so
                # plainly: the player falls back to the origin, which is
                # slower and completely correct.
                return self._json(503, {'ok': False, 'error': 'no signing key'})
            base = ''
            try:
                with open(EDGE_BASE_PATH, encoding='utf-8') as f:
                    base = f.read().strip()
            except OSError:
                pass
            return self._json(200, {'ok': True, 'token': token,
                                    'exp': exp, 'base': base})
        if DEV and not path.startswith('/api/'):
            return self.serve_static(path)
        if path == '/api/status':
            # The player asks about the ids it submitted; it holds those in
            # localStorage, so nothing here has to remember who anyone is.
            ids = [i for i in (parse_qs(u.query).get('ids', [''])[0]).split(',') if i][:60]
            results = self._results()
            done = self._done_ids()
            entries = {e['id']: e for e in self._queue_entries() if e.get('id')}
            out = {}
            for i in ids:
                if i in results:
                    r = results[i]
                    out[i] = {'state': r.get('state', 'done'),
                              'title': r.get('title'), 'note': r.get('note')}
                elif i in done:
                    # Finished, but before results.jsonl existed. Without this
                    # branch requests.jsonl -- which is append-only and never
                    # trimmed -- reported every song ever asked for as still
                    # queued, so the player's bell said "waiting" forever even
                    # for songs that had been live for days.
                    e = entries.get(i, {})
                    out[i] = {'state': 'done', 'title': e.get('song'), 'note': None}
                elif i in entries:
                    out[i] = {'state': 'queued'}
                else:
                    out[i] = {'state': 'unknown'}
            return self._json(200, {'ok': True, 'status': out})
        return self._json(404, {'error': 'not found'})

    def log_message(self, fmt, *args):
        pass          # Caddy already logs every request that reaches us


def main():
    global DEV, WEB_DIR, USERS_FILE, SESSION_KEY_FILE
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8931)
    # Loopback by default: on the VPS Caddy is the only thing in front, and
    # nothing else should reach this. --dev testing on a PHONE needs
    # --host 0.0.0.0 and the laptop's LAN address instead of localhost.
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--queue', default='/opt/beatznbox/queue/requests.jsonl')
    ap.add_argument('--web', default='/opt/beatznbox/web')
    ap.add_argument('--dev', action='store_true',
                    help='no Caddy in front: ignore X-Beatz-User, use the '
                         'session cookie only, and serve the player from --web')
    a = ap.parse_args()
    DEV = a.dev
    WEB_DIR = a.web
    Handler.queue_path = a.queue
    # users.json and session.key sit beside the queue files unless the
    # environment names them. On the VPS that is /opt/beatznbox/queue/../,
    # which is where they already are; on a laptop it is the scratch
    # directory, so a --dev run writes nothing outside it.
    qdir = os.path.dirname(os.path.abspath(a.queue))
    if not USERS_FILE:
        USERS_FILE = os.path.join(qdir, 'users.json')
    if not SESSION_KEY_FILE:
        SESSION_KEY_FILE = os.path.join(qdir, 'session.key')
    os.makedirs(qdir, exist_ok=True)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
