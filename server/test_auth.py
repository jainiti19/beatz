#!/usr/bin/env python3
"""End-to-end tests for the queue service's auth: signup, login, sessions,
per-user scopes and the users file.

Runs the real service in --dev on a scratch directory, so nothing here
touches /opt/beatznbox or needs Caddy:

    python3 server/test_auth.py -v

Every test here is a regression test for a bug found on 30 Sep 2026, in a
change set that had shipped with none of this covered:

1. signup/login replies began with the Set-Cookie header, ahead of the status
   line, so the response was not valid HTTP and every browser refused it.
   ("could not reach the server")
2. --dev ignored the session cookie and still trusted X-Beatz-User, so the
   account flow could not be tested locally at all.
3. POST /api/users rewrote users.json as {"users": ...}, deleting every
   account in it.
4. The auth rate limit counted every attempt per client_address, which is
   127.0.0.1 behind Caddy -- one shared budget for the whole site, spent by
   successful logins too.

What is NOT covered here, because it cannot be: --dev has no Caddy, so a
`viewer` login (the shared `beatz`) cannot be produced. The viewer-is-refused
path is the do_POST gate at SHARED_WRITES, and its server-side logic is
unchanged by the fixes.
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE = os.path.join(HERE, 'queue-service.py')
WEB = os.path.join(os.path.dirname(HERE), 'web')

ALICE = 'password123'
ROOT = 'rootpass123'


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def cookie_value(set_cookie):
    """The beatz_session value out of a Set-Cookie header, or None."""
    if not set_cookie or 'beatz_session=' not in set_cookie:
        return None
    return set_cookie.split('beatz_session=')[1].split(';')[0] or None


class AuthFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='beatz-auth-test-')
        cls.port = free_port()
        # An admin ACCOUNT: signup only ever creates editors, and in --dev the
        # Caddy header is (correctly) ignored, so this is the only way to
        # exercise the admin-only /api/users endpoint.
        import bcrypt
        cls.users_file = os.path.join(cls.tmp, 'users.json')
        with open(cls.users_file, 'w', encoding='utf-8') as f:
            json.dump({'accounts': {'root': {
                'pw': bcrypt.hashpw(ROOT.encode(), bcrypt.gensalt(rounds=4)).decode(),
                'role': 'admin', 'created': 'x'}}}, f)
        cls.proc = subprocess.Popen(
            [sys.executable, SERVICE, '--dev', '--port', str(cls.port),
             '--queue', os.path.join(cls.tmp, 'requests.jsonl'), '--web', WEB],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.time() + 10
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                out = cls.proc.stdout.read().decode()
                raise AssertionError('service died on startup:\n' + out)
            try:
                socket.create_connection(('127.0.0.1', cls.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.1)
        raise AssertionError('service did not start within 10s')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def request(self, method, path, body=None, cookie=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        h = dict(headers or {})
        payload = None
        if body is not None:
            payload = json.dumps(body)
            h['Content-Type'] = 'application/json'
        if cookie:
            h['Cookie'] = 'beatz_session=' + cookie
        conn.request(method, path, body=payload, headers=h)
        r = conn.getresponse()
        raw = r.read()
        status, set_cookie = r.status, r.getheader('Set-Cookie')
        conn.close()
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {'raw': raw[:200].decode('utf-8', 'replace')}
        return status, data, set_cookie

    # -- the flow ----------------------------------------------------------

    def test_01_signup_then_me(self):
        status, d, sc = self.request('POST', '/api/signup',
                                     {'user': 'alice', 'password': ALICE})
        self.assertEqual(status, 200, d)
        alice = cookie_value(sc)
        self.assertTrue(alice, 'signup must set a session cookie: %r' % sc)
        type(self).alice = alice

        status, me, _ = self.request('GET', '/api/me', cookie=alice)
        self.assertEqual(status, 200, me)
        self.assertEqual(me['user'], 'alice')
        self.assertTrue(me['account'])
        self.assertTrue(me['canEditOwn'], 'an account may edit its own set')
        self.assertFalse(me['canEditShared'], 'an account may not edit the shared set')

    def test_02_signup_response_is_valid_http(self):
        """Bug 1: the raw response must begin with a status line, not with
        Set-Cookie. curl said 'Received HTTP/0.9'; a browser's fetch said
        'Response does not match the HTTP/1.1 protocol'."""
        body = json.dumps({'user': 'rawcheck', 'password': ALICE}).encode()
        s = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        s.sendall(b'POST /api/signup HTTP/1.1\r\nHost: beatz\r\n'
                  b'Content-Type: application/json\r\n'
                  b'Content-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
        data = s.recv(200)
        s.close()
        self.assertTrue(data.startswith(b'HTTP/1.'), data[:120])

    def test_03_wrong_password_then_right(self):
        """A failed login is 401; a successful one still works straight after
        (a success must not spend the rate-limit budget -- bug 4)."""
        status, d, _ = self.request('POST', '/api/login',
                                    {'user': 'alice', 'password': 'wrongpass1'})
        self.assertEqual(status, 401, d)
        status, d, sc = self.request('POST', '/api/login',
                                     {'user': 'alice', 'password': ALICE})
        self.assertEqual(status, 200, d)
        self.assertTrue(cookie_value(sc))

    def test_04_personal_playlist_round_trip(self):
        """An editor/account writes their OWN set; the shared set is refused
        and stays untouched."""
        cookie = type(self).alice
        status, d, _ = self.request('POST', '/api/playlists',
                                    {'playlists': {'My Set': ['song_a']}, 'rev': 0,
                                     'scope': 'user'}, cookie=cookie)
        self.assertEqual(status, 200, d)
        status, d, _ = self.request('GET', '/api/playlists', cookie=cookie)
        self.assertEqual(status, 200, d)
        self.assertEqual(d['mine'].get('My Set'), ['song_a'])
        self.assertEqual(d.get('playlists'), {}, 'the shared set must be untouched')
        status, d, _ = self.request('POST', '/api/playlists',
                                    {'playlists': {'Sneak': []}, 'rev': d['rev'],
                                     'scope': 'shared'}, cookie=cookie)
        self.assertEqual(status, 403, d)

    def test_05_dev_ignores_the_caddy_header(self):
        """Bug 2: in --dev there is no Caddy, so X-Beatz-User must not be
        honoured -- anyone on the LAN could claim to be admin."""
        status, d, _ = self.request('POST', '/api/users',
                                    {'user': 'bob', 'role': 'viewer'},
                                    headers={'X-Beatz-User': 'admin'})
        self.assertEqual(status, 403, d)

    def test_06_users_write_preserves_accounts(self):
        """Bug 3: writing a role to users.json must not delete the accounts
        living in the same file."""
        status, d, sc = self.request('POST', '/api/login',
                                     {'user': 'root', 'password': ROOT})
        self.assertEqual(status, 200, d)
        root = cookie_value(sc)
        self.assertTrue(root)
        status, d, _ = self.request('POST', '/api/users',
                                    {'user': 'carol', 'role': 'viewer'}, cookie=root)
        self.assertEqual(status, 200, d)
        with open(self.users_file, encoding='utf-8') as f:
            users = json.load(f)
        self.assertIn('alice', users.get('accounts', {}), 'accounts were deleted')
        self.assertIn('root', users.get('accounts', {}))
        self.assertEqual(users.get('users', {}).get('carol'), {'role': 'viewer'})

    def test_07_logout_clears_the_cookie(self):
        status, d, sc = self.request('POST', '/api/logout', {},
                                     cookie=type(self).alice)
        self.assertEqual(status, 200, d)
        self.assertIn('Max-Age=0', sc or '', 'logout must expire the cookie: %r' % sc)
        status, me, _ = self.request('GET', '/api/me')
        self.assertIsNone(me.get('user'), 'with no cookie there is no login')

    def test_08_personal_clip_round_trip(self):
        """Clips follow the same rule as playlists: an editor/account writes
        its own, the shared set is refused."""
        status, d, sc = self.request('POST', '/api/login',
                                     {'user': 'alice', 'password': ALICE})
        self.assertEqual(status, 200, d)
        cookie = cookie_value(sc)
        key = 'My Set::song_a'
        status, d, _ = self.request('POST', '/api/clips',
                                    {'key': key, 'clip': {'start': 1.5, 'end': 30.0},
                                     'scope': 'user'}, cookie=cookie)
        self.assertEqual(status, 200, d)
        status, d, _ = self.request('GET', '/api/clips', cookie=cookie)
        self.assertEqual(d['mine'].get(key), {'start': 1.5, 'end': 30.0})
        self.assertEqual(d.get('clips'), {}, 'the shared clips must be untouched')
        status, d, _ = self.request('POST', '/api/clips',
                                    {'key': key, 'clip': {'start': 2, 'end': 3},
                                     'scope': 'shared'}, cookie=cookie)
        self.assertEqual(status, 403, d)


if __name__ == '__main__':
    unittest.main(verbosity=2)
