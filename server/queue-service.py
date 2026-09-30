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

# How long a login lasts. Long, because this is a party app and nobody wants
# to type a password every time they open it; the cookie is HttpOnly and the
# site is behind Caddy, so the exposure is small.
SESSION_TTL = 30 * 24 * 3600

# Signup and login are the only endpoints an unauthenticated caller can reach,
# so they are the only ones worth guessing at. A small in-memory counter per
# IP blunts that without a dependency. Not a substitute for fail2ban.
AUTH_ATTEMPTS = {}          # ip -> [timestamps]
AUTH_ATTEMPTS_LOCK = threading.Lock()
AUTH_MAX = 10               # attempts
AUTH_WINDOW = 15 * 60       # seconds

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

def valid_login(name):
    """A login name. Both kinds of login are restricted to the same charset --
    add-user.sh's Caddy logins and the signup form -- so one predicate covers
    both. It says nothing about whether the name exists: Caddy logins are not
    visible to this service, so an invitation to a name that has not signed up
    yet is allowed and simply waits."""
    return bool(name) and isinstance(name, str) and len(name) <= 40 \
        and re.fullmatch(r'[A-Za-z0-9_.-]+', name) is not None


def share_role(shares, user, owner, name):
    """'view' | 'edit' | None: what `user` may do with `owner`'s `name`."""
    if not user or not owner or not name or user == owner:
        return None
    rec = ((shares.get(user) or {}).get(owner) or {}).get(name)
    return rec if rec in SHARE_ROLES else None


def visible_shares(user_pl, shares, user):
    """({name: {'owner', 'role'}}, [shadowed]) for playlists shared to `user`.

    Visible means the owner still HAS that playlist. A share whose name the
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
            if name not in (user_pl.get(owner) or {}):
                continue                    # the owner deleted it; the share is dead
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


def shared_entries(buckets, user_pl, shares, user):
    """{key: value} taken from the owners' buckets, for every playlist shared
    to `user` -- clips and presets alike. The keys are the same bare
    "<name>::<song>" the caller already uses for their own, so nothing
    downstream needs to know who owns a playlist."""
    meta, _ = visible_shares(user_pl, shares, user)
    by_owner = {}
    for name, m in meta.items():
        by_owner.setdefault(m['owner'], set()).add(name)
    out = {}
    for owner, names in by_owner.items():
        out = merge_shared_entries(out, buckets.get(owner) or {}, names)
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
    Caddy logins still work) on a box where bcrypt is not installed yet."""
    import bcrypt
    return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('ascii')


def check_password(pw, hashed):
    import bcrypt
    try:
        return bcrypt.checkpw(pw.encode('utf-8'), hashed.encode('ascii'))
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


def make_session(user):
    """v1.<user>.<exp>.<hmac>. The user is base64url'd so a name with a dot in
    it cannot be mistaken for the separator."""
    exp = int(time.time()) + SESSION_TTL
    u = base64.urlsafe_b64encode(user.encode('utf-8')).decode('ascii').rstrip('=')
    msg = f'v1.{u}.{exp}'
    sig = hmac.new(session_key(), msg.encode('ascii'), hashlib.sha256).hexdigest()
    return f'{msg}.{sig}'


def read_session(value):
    """The login name in a session cookie, or None if it is absent, malformed,
    expired or not signed by us."""
    if not value:
        return None
    parts = value.split('.')
    if len(parts) != 4 or parts[0] != 'v1':
        return None
    _, u, exp, sig = parts
    msg = f'v1.{u}.{exp}'
    want = hmac.new(session_key(), msg.encode('ascii'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, want):
        return None
    try:
        if int(exp) < time.time():
            return None
        pad = '=' * (-len(u) % 4)
        return base64.urlsafe_b64decode(u + pad).decode('utf-8')
    except Exception:
        return None


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

    def _session_cookie(self, user):
        """The Set-Cookie VALUE for a login, to hand to _json."""
        bits = [f'beatz_session={make_session(user)}', 'Path=/', 'HttpOnly',
                'SameSite=Lax', f'Max-Age={SESSION_TTL}']
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
        sess = read_session(self._cookie('beatz_session'))
        if sess:
            acct = accounts().get(sess)
            if acct:
                return sess, (acct.get('role') if acct.get('role') in ROLES else 'editor')
            # A cookie for an account that has since been deleted: treat it
            # as no login at all rather than falling through to the header,
            # which would silently promote it to a Caddy login.
            return None, 'viewer'
        # In --dev there is no Caddy, so the header is ignored entirely --
        # trusting it there would let anyone on the LAN claim to be admin.
        if DEV:
            return None, 'viewer'
        user = self.headers.get('X-Beatz-User')
        if user is None:
            if self.headers.get('X-Forwarded-For') is None and not DEV:
                return None, 'admin'
            return None, 'viewer'
        user = user.strip()
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

    def _playlist_payload(self, shared, user_pl, shares, links, rev, user):
        """What GET returns, what every 200 returns, and (with `error`) what a
        409 returns -- so a stale client reconciles from exactly the state it
        would have got from a fresh load. Only the caller's OWN shares and
        links are in here: nobody sees who else has access to anything."""
        meta, shadowed = visible_shares(user_pl, shares, user)
        mine = dict(user_pl.get(user, {}) if user else {})
        for name, m in meta.items():
            mine[name] = (user_pl.get(m['owner']) or {}).get(name, [])
        my_links = {t: {'name': r.get('name'), 'role': r.get('role'),
                        'created': r.get('created')}
                    for t, r in links.items()
                    if isinstance(r, dict) and r.get('owner') == user}
        return {'ok': True, 'playlists': shared, 'mine': mine,
                'sharedMeta': meta, 'shadowed': shadowed,
                'myShares': owned_shares(shares, user), 'myLinks': my_links,
                'rev': rev}

    def _share_target(self, data, key, user, role):
        """(scope, owner, denial) for a preset or clip write.

        Resolves the caller's own bucket vs the shared set vs a grant on
        someone else's playlist, so both handlers agree. `denial` is a
        (code, error) pair when the write may not proceed at all."""
        scope = data.get('scope') or 'shared'
        owner = (data.get('owner') or '').strip()
        if scope == SHARE_SCOPE:
            if not valid_login(owner):
                return scope, owner, (400, 'owner is required')
            with PLAYLISTS_LOCK:
                _, user_pl, shares, _, _ = self._read_playlists()
                name = key_playlist(key)
                ok = (share_role(shares, user, owner, name) == 'edit'
                      and name in (user_pl.get(owner) or {}))
            return scope, owner, None if ok else (403, 'read-only')
        return scope, owner, scope_allowed(scope, user, role, None)

    def get_playlists(self):
        shared, user_pl, shares, links, rev = self._read_playlists()
        # The caller only ever sees their own bucket and what has been shared
        # with them, never anyone else's. The shared set is returned to
        # everyone, since that is what "shared" means.
        user, _ = self._who()
        return self._json(200, self._playlist_payload(shared, user_pl, shares, links, rev, user))

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
                # never delete one.
                if not valid_login(owner):
                    return self._json(400, {'error': 'owner is required'})
                bucket = user_pl.get(owner) or {}
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
                    body = self._playlist_payload(shared, user_pl, shares, links, rev, user)
                    body.pop('ok', None)
                    body['error'] = 'stale'
                    return self._json(409, body)

            if scope == 'shared':
                shared = clean
            elif scope == 'user':
                user_pl[user] = clean
                # Shares and links for playlists that no longer exist go with
                # them: a link to a deleted playlist must die with the playlist.
                for recipient, by_owner in list(shares.items()):
                    held = by_owner.get(user)
                    if not isinstance(held, dict):
                        continue
                    for gone in [n for n in list(held) if n not in clean]:
                        del held[gone]
                    if not held:
                        del by_owner[user]
                    if not by_owner:
                        del shares[recipient]
                for token in [t for t, r in links.items()
                              if isinstance(r, dict) and r.get('owner') == user
                              and r.get('name') not in clean]:
                    del links[token]
            else:
                bucket = user_pl.setdefault(owner, {})
                bucket.update(clean)
            rev += 1
            self._write_playlists(shared, user_pl, shares, links, rev)
            return self._json(200, self._playlist_payload(shared, user_pl, shares, links, rev, user))

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
            _, user_pl, shares, _, _ = self._read_playlists()
        # A collaborator sees the owner's mixes for the playlists shared with
        # them, under the same bare keys as their own -- the client never has
        # to know who owns a playlist. Their own entry wins a clash.
        mine = shared_entries(user_pr, user_pl, shares, user) if user else {}
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
            target = shared if scope == 'shared' else user_pr.setdefault(bucket_user, {})
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
            _, user_pl, shares, _, _ = self._read_playlists()
        # Same merge as presets: the owner's clips for a playlist shared with
        # the caller arrive under the same bare keys, own entry winning.
        mine = shared_entries(user_cl, user_pl, shares, user) if user else {}
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
            target = shared if scope == 'shared' else user_cl.setdefault(bucket_user, {})
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
        """{code: session}, expired ones dropped. Kept in a file rather than in
        memory so a service restart mid-set does not orphan a link somebody is
        already following. Callers hold LIVE_LOCK."""
        try:
            with open(self._live_path(), encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            return {}
        if not isinstance(d, dict):
            return {}
        now = time.time()
        return {c: s for c, s in d.items()
                if isinstance(s, dict) and now - float(s.get('updated') or 0) < LIVE_TTL}

    def _live_write(self, sessions):
        tmp = self._live_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(sessions, f, ensure_ascii=False)
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
        code = str(data.get('code') or '').strip()
        with LIVE_LOCK:
            sessions = self._live_load()
            if not code or code not in sessions or sessions[code].get('user') != user:
                code = secrets.token_urlsafe(8)     # 11 chars: the whole secret
                sessions = {c: s for c, s in sessions.items() if s.get('user') != user}
            sessions[code] = {'user': user, 'dir': dirname,
                              'title': str(data.get('title') or '')[:80],
                              'pos': round(pos, 2), 'playing': bool(data.get('playing')),
                              'tempo': round(tempo, 3), 'updated': time.time()}
            if len(sessions) > LIVE_MAX:
                for c, _s in sorted(sessions.items(),
                                    key=lambda kv: kv[1].get('updated') or 0)[:len(sessions) - LIVE_MAX]:
                    del sessions[c]
            self._live_write(sessions)
        return self._json(200, {'ok': True, 'code': code})

    def post_live_stop(self):
        user, _ = self._who()
        with LIVE_LOCK:
            sessions = self._live_load()
            mine = [c for c, s in sessions.items() if s.get('user') == user]
            for c in mine:
                del sessions[c]
            if mine:
                self._live_write(sessions)
        return self._json(200, {'ok': True})

    def get_live(self, code):
        """PUBLIC -- no login, no Caddy. The code is the credential. `age` is
        how old the snapshot is, in ms, so the follower can extrapolate without
        trusting its own clock against the server's."""
        with LIVE_LOCK:
            s = self._live_load().get(code)
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
            s = self._live_load().get(code)
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
        user, _ = self._who()
        if not user:
            return self._json(400, {'error': 'login required'})
        with PLAYLISTS_LOCK:
            shared, user_pl, shares, links, rev = self._read_playlists()
            if data.get('revoke'):
                token = str(data.get('token') or '').strip()
                rec = links.get(token) if token else None
                if not isinstance(rec, dict) or rec.get('owner') != user:
                    return self._json(404, {'error': 'no such link'})
                del links[token]
                token = None
            else:
                name = str(data.get('name') or '').strip()[:60]
                lrole = data.get('role')
                if lrole not in SHARE_ROLES:
                    return self._json(400, {'error': 'role must be view or edit'})
                if name not in (user_pl.get(user) or {}):
                    return self._json(404, {'error': 'no such playlist'})
                mine_links = [r for r in links.values()
                              if isinstance(r, dict) and r.get('owner') == user]
                if len(mine_links) >= MAX_SHARES_PER_PLAYLIST:
                    return self._json(400, {'error': 'too many share links'})
                token = secrets.token_urlsafe(12)
                links[token] = {'owner': user, 'name': name, 'role': lrole,
                                'created': int(time.time())}
            rev += 1
            self._write_playlists(shared, user_pl, shares, links, rev)
            body = self._playlist_payload(shared, user_pl, shares, links, rev, user)
            body['token'] = token        # the one just made, or None on a revoke
            return self._json(200, body)

    def post_share_claim(self):
        """The recipient's half: opening a link. Idempotent, and it never
        downgrades -- someone with edit who opens a view link keeps edit --
        so a second claim costs no rev."""
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        user, _ = self._who()
        if not user:
            return self._json(400, {'error': 'login required'})
        token = str(data.get('token') or '').strip()
        with PLAYLISTS_LOCK:
            shared, user_pl, shares, links, rev = self._read_playlists()
            rec = links.get(token) if token else None
            if not isinstance(rec, dict):
                return self._json(404, {'error': 'that link is not valid'})
            owner, name, lrole = rec.get('owner'), rec.get('name'), rec.get('role')
            if lrole not in SHARE_ROLES or not valid_login(owner) or not isinstance(name, str):
                return self._json(404, {'error': 'that link is not valid'})
            if name not in (user_pl.get(owner) or {}):
                return self._json(404, {'error': 'that playlist no longer exists'})
            if owner == user:
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
            body = self._playlist_payload(shared, user_pl, shares, links, rev, user)
            body['claimed'] = {'owner': owner, 'name': name, 'role': held.get(name)}
            return self._json(200, body)

    def post_shares(self):
        """The owner's grip on their own playlist: remove one person, or change
        their role. A recipient uses the same call to leave."""
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return
        user, _ = self._who()
        if not user:
            return self._json(400, {'error': 'login required'})
        name = str(data.get('name') or '').strip()[:60]
        if not name:
            return self._json(400, {'error': 'playlist is required'})
        with PLAYLISTS_LOCK:
            shared, user_pl, shares, links, rev = self._read_playlists()
            if data.get('leave'):
                owner = str(data.get('owner') or '').strip()
                if not valid_login(owner):
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
                if name not in (user_pl.get(user) or {}):
                    return self._json(404, {'error': 'no such playlist'})
                recipient = str(data.get('user') or '').strip()
                if not valid_login(recipient) or recipient == user:
                    return self._json(400, {'error': 'bad user name'})
                held = (shares.get(recipient) or {}).get(user)
                grant = data.get('role')
                changed = False
                if grant in SHARE_ROLES:
                    if held is None:
                        held = shares.setdefault(recipient, {}).setdefault(user, {})
                    changed = held.get(name) != grant
                    held[name] = grant
                elif isinstance(held, dict) and name in held:
                    del held[name]
                    changed = True
                    if not held:
                        del shares[recipient][user]
                    if not shares.get(recipient):
                        del shares[recipient]
                if changed:
                    rev += 1
                    self._write_playlists(shared, user_pl, shares, links, rev)
            return self._json(200, self._playlist_payload(shared, user_pl, shares, links, rev, user))

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

    # ---- accounts: signup, login, logout -----------------------------
    # The only endpoints an unauthenticated caller can reach. Everything else
    # needs either a session cookie or a Caddy login.
    def _auth_body(self):
        """(user, password) from the request body, or (None, None) after
        having already sent an error."""
        data, err = self._read_json(MAX_BODY)
        if err is not None:
            return None, None
        user = (data.get('user') or '').strip()
        pw = data.get('password') or ''
        if not user or len(user) > 40 or not re.fullmatch(r'[A-Za-z0-9_.-]+', user):
            self._json(400, {'error': 'User name must be letters, digits, dot, dash or underscore.'})
            return None, None
        if len(pw) < 8:
            self._json(400, {'error': 'Password must be at least 8 characters.'})
            return None, None
        return user, pw

    def post_signup(self):
        ip = self._client_ip()
        if not auth_check(ip):
            return self._json(429, {'error': 'Too many attempts. Try again later.'})
        user, pw = self._auth_body()
        if user is None:
            return
        with USERS_LOCK:
            d = _read_users_file()
            accts = d.get(ACCOUNTS_KEY) if isinstance(d.get(ACCOUNTS_KEY), dict) else {}
            # A name already used by a Caddy login is refused too: otherwise a
            # signup could shadow `admin` and the two would disagree about who
            # that is.
            if user in accts or user in admins() or user in users():
                return self._json(409, {'error': 'That name is taken.'})
            try:
                accts[user] = {'pw': hash_password(pw), 'role': 'editor',
                               'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            except ImportError:
                return self._json(500, {'error': 'Server is missing bcrypt; ask the admin to install it.'})
            d[ACCOUNTS_KEY] = accts
            _write_users(d)
        return self._json(200, {'ok': True, 'user': user, 'role': 'editor'},
                          cookie=self._session_cookie(user))

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
                          cookie=self._session_cookie(user))

    def post_logout(self):
        # Clears the browser's cookie. The token itself stays valid until it
        # expires: HMAC sessions are stateless, so there is nothing to revoke
        # server-side. Acceptable here -- 30-day TTL, HttpOnly, and this is a
        # party app whose worst-case loss is someone else's playlists.
        return self._json(200, {'ok': True}, cookie=self._expired_session_cookie())

    def get_me(self):
        """Who the caller is, for the player to decide what to show. Distinct
        from /api/whoami, which predates accounts and is kept as it was."""
        user, role = self._who()
        acct = accounts().get(user) if user else None
        return self._json(200, {
            'ok': True,
            'user': user,
            'role': role,
            'account': bool(acct),
            'canEditShared': role == 'admin',
            'canEditOwn': role in ('admin', 'editor'),
        })

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
        if path == '/api/report':
            return self.post_report()
        if path != '/api/request':
            return self._json(404, {'error': 'not found'})
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

    def post_lyrics(self):
        """Words pasted in the player for a song LRCLIB does not carry.

        Written to a drop directory rather than the request queue: the watcher
        treats these differently — no download, no separation, just align the
        words against stems that already exist."""
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
    ThreadingHTTPServer(('127.0.0.1', a.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
