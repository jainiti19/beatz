#!/usr/bin/env python3
"""Accept song requests from the web player and append them to a queue file.

Runs on the VPS, bound to localhost only — Caddy reverse-proxies /api/ to it,
so every request has already passed the site's basic auth. That is the only
authentication there is: this service trusts whatever reaches it.

The queue is a JSONL file rather than a database because the consumer is a
laptop polling over SSH, and a text file is something you can read, fix by hand
and recover from. Nothing here processes a song; it only records the ask.

Usage: queue-service.py [--port 8931] [--queue /opt/beatznbox/queue/requests.jsonl]
"""
import argparse, json, os, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 4096          # a request is a song name, not a payload
MAX_LYRICS = 32768       # a long song is a few KB; this is generous
MAX_FIELD = 120
MAX_PENDING = 50         # a full queue means something is wrong upstream

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


class Handler(BaseHTTPRequestHandler):
    queue_path = None

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return None, self._json(400, {'error': 'bad length'})
        if length <= 0 or length > limit:
            return None, self._json(413, {'error': 'body too large'})
        try:
            return json.loads(self.rfile.read(length).decode('utf-8')), None
        except Exception:
            return None, self._json(400, {'error': 'bad json'})

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

    def do_POST(self):
        path = self.path.rstrip('/')
        if path == '/api/lyrics':
            return self.post_lyrics()
        if path == '/api/playlists':
            return self.post_playlists()
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

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        path = u.path.rstrip('/')
        if path == '/api/health':
            return self._json(200, {'ok': True, 'pending': self._pending()})
        if path == '/api/playlists':
            return self.get_playlists()
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
