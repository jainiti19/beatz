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
        if not os.path.exists(self.queue_path):
            return 0
        with open(self.queue_path, encoding='utf-8') as f:
            return sum(1 for line in f if line.strip())

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

    def do_POST(self):
        path = self.path.rstrip('/')
        if path == '/api/lyrics':
            return self.post_lyrics()
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
        if self.path.rstrip('/') == '/api/health':
            return self._json(200, {'ok': True, 'pending': self._pending()})
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
