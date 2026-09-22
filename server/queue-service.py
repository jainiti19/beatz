#!/usr/bin/env python3
"""Accept song requests from the web player and append them to a queue file.

Runs on the VPS, bound to localhost only — Caddy reverse-proxies /api/ to it,
so every request has already passed the site's basic auth. Caddy also names
the login in X-Beatz-User; since 23 Sep only an admin login may write the
shared playlists, setups and clips (see "who may change the shared set").

The queue is a JSONL file rather than a database because the consumer is a
laptop polling over SSH, and a text file is something you can read, fix by hand
and recover from. Nothing here processes a song; it only records the ask.

Usage: queue-service.py [--port 8931] [--queue /opt/beatznbox/queue/requests.jsonl]
"""
import argparse, base64, hashlib, hmac, json, os, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRESETS_LOCK = threading.Lock()
CLIPS_LOCK = threading.Lock()

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

# The endpoints that write what everyone shares. Everything else stays open to
# every login: requests, fault reports and pasted lyrics are how testers help,
# and each only ever appends a note for the watcher to act on.
SHARED_WRITES = {'/api/playlists', '/api/presets', '/api/clips'}


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

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        user = self.headers.get('X-Beatz-User')
        if user is None:
            if self.headers.get('X-Forwarded-For') is None:
                return None, 'admin'
            return None, 'viewer'
        user = user.strip()
        return user, ('admin' if user and user in admins() else 'viewer')

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
        try:
            with open(self._playlists_path(), encoding='utf-8') as f:
                d = json.load(f)
            return d.get('playlists', {}), int(d.get('rev', 0))
        except Exception:
            return {}, 0

    def get_playlists(self):
        pl, rev = self._read_playlists()
        return self._json(200, {'ok': True, 'playlists': pl, 'rev': rev})

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

        cur, rev = self._read_playlists()
        # Last-writer-wins would silently bin a playlist someone else just made
        # from another phone. The client sends the rev it started from; a stale
        # one gets the current state back and re-sends its change on top.
        sent = data.get('rev')
        if sent is not None and int(sent) != rev:
            return self._json(409, {'error': 'stale', 'playlists': cur, 'rev': rev})

        rev += 1
        tmp = self._playlists_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'playlists': clean, 'rev': rev}, f, ensure_ascii=False)
        os.replace(tmp, self._playlists_path())     # atomic: no half-written file
        return self._json(200, {'ok': True, 'playlists': clean, 'rev': rev})

    # ---- saved song setups -------------------------------------------
    # "Save Setup" lived in each browser's localStorage, so a mix saved on a
    # laptop was missing on the NUC driving the speakers. One shared file, like
    # playlists. Unlike playlists, a write carries ONE setup rather than the
    # whole map: two people saving different songs at once is the normal case
    # here, and neither should need to know about the other's.
    def _presets_path(self):
        return os.path.join(os.path.dirname(self.queue_path), 'presets.json')

    def _read_presets(self):
        try:
            with open(self._presets_path(), encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def get_presets(self):
        return self._json(200, {'ok': True, 'presets': self._read_presets()})

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
        # Read-modify-write under a lock: the server is threaded, and two saves
        # landing together would otherwise each write a map missing the other.
        with PRESETS_LOCK:
            presets = self._read_presets()
            if clean is None:
                presets.pop(key, None)
            else:
                if key not in presets and len(presets) >= 5000:
                    return self._json(400, {'error': 'too many saved setups'})
                presets[key] = clean
            tmp = self._presets_path() + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(presets, f, ensure_ascii=False)
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
        try:
            with open(self._clips_path(), encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def get_clips(self):
        return self._json(200, {'ok': True, 'clips': self._read_clips()})

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
        # Read-modify-write under a lock, as for presets: two people trimming
        # different songs at once must not each write a map missing the other.
        with CLIPS_LOCK:
            clips = self._read_clips()
            if clean is None:
                clips.pop(key, None)
            else:
                if key not in clips and len(clips) >= 5000:
                    return self._json(400, {'error': 'too many clips'})
                clips[key] = clean
            tmp = self._clips_path() + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(clips, f, ensure_ascii=False)
            os.replace(tmp, self._clips_path())     # atomic: no half-written file
        return self._json(200, {'ok': True, 'clip': clean})

    def do_POST(self):
        path = self.path.rstrip('/')
        # The shared set is Iti's and Karan's (see SHARED_WRITES). Refused
        # before the body is read: nothing a viewer sends here is used. The
        # player expects this exact shape and keeps the change on the
        # viewer's own device instead of showing an error.
        if path in SHARED_WRITES and self._who()[1] != 'admin':
            return self._json(403, {'error': 'read-only', 'role': 'viewer'})
        if path == '/api/lyrics':
            return self.post_lyrics()
        if path == '/api/playlists':
            return self.post_playlists()
        if path == '/api/presets':
            return self.post_presets()
        if path == '/api/clips':
            return self.post_clips()
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
                                    'local': user is None and role == 'admin'})
        if path == '/api/playlists':
            return self.get_playlists()
        if path == '/api/presets':
            return self.get_presets()
        if path == '/api/clips':
            return self.get_clips()
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
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8931)
    ap.add_argument('--queue', default='/opt/beatznbox/queue/requests.jsonl')
    a = ap.parse_args()
    Handler.queue_path = a.queue
    os.makedirs(os.path.dirname(a.queue), exist_ok=True)
    ThreadingHTTPServer(('127.0.0.1', a.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
