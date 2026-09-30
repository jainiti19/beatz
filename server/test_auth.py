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


class ServiceCase(unittest.TestCase):
    """A real service in --dev on a scratch queue directory.

    Subclasses declare `seed_accounts` ({login: (password, role)}) and it is
    written to users.json before the service starts -- signup only ever makes
    editors, so a role other than that has to be seeded. Everything else about
    a case lives in its tests."""

    seed_accounts = {}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='beatz-auth-test-')
        cls.port = free_port()
        cls.users_file = os.path.join(cls.tmp, 'users.json')
        if cls.seed_accounts:
            import bcrypt
            with open(cls.users_file, 'w', encoding='utf-8') as f:
                json.dump({'accounts': {
                    login: {'pw': bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode(),
                            'role': role, 'created': 'x'}
                    for login, (pw, role) in cls.seed_accounts.items()}}, f)
        cls.proc = subprocess.Popen(
            [sys.executable, SERVICE, '--dev', '--port', str(cls.port),
             '--queue', os.path.join(cls.tmp, 'requests.jsonl'), '--web', WEB],
            stdout=open(os.path.join(cls.tmp, 'server.log'), 'wb'),
            stderr=subprocess.STDOUT)
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

    def login_cookie(self, user, pw):
        status, d, sc = self.request('POST', '/api/login', {'user': user, 'password': pw})
        self.assertEqual(status, 200, d)
        cookie = cookie_value(sc)
        self.assertTrue(cookie, 'login did not set a cookie: %r' % sc)
        return cookie

    def signup_cookie(self, user, pw=ALICE):
        status, d, sc = self.request('POST', '/api/signup',
                                     {'user': user, 'password': pw})
        self.assertEqual(status, 200, d)
        return cookie_value(sc)


class AuthFlow(ServiceCase):
    """The login flow itself: signup, sessions, per-user scopes, the users
    file. A Caddy login cannot be produced in --dev -- there is no Caddy, and
    the header is correctly ignored -- so a viewer-role login is exercised in
    Sharing instead, with a seeded account."""

    seed_accounts = {'root': (ROOT, 'admin')}

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


class Sharing(ServiceCase):
    """Share links: create → claim → collaborate, plus revoke and leave.

    The permission matrix only exists server-side, so these run against the
    real service, as AuthFlow does. `dave` is a viewer-role login -- the shape
    of the Caddy `beatz` login, seeded because signup only ever makes editors.
    """

    seed_accounts = {
        'alice': (ALICE, 'editor'),
        'bob': ('bobpass123', 'editor'),
        'carol': ('carolpass123', 'editor'),
        'dave': ('davepass123', 'viewer'),
    }

    # -- helpers -----------------------------------------------------------

    def playlists(self, cookie):
        status, d, _ = self.request('GET', '/api/playlists', cookie=cookie)
        self.assertEqual(status, 200, d)
        return d

    def own_only(self, cookie):
        """The caller's own playlists, without what has been shared with them
        -- exactly what the page must post back on a whole-map save."""
        d = self.playlists(cookie)
        meta = d.get('sharedMeta') or {}
        return {n: dirs for n, dirs in d['mine'].items() if n not in meta}

    def own(self, cookie, body):
        """A whole-map write of the caller's own bucket."""
        rev = self.playlists(cookie)['rev']
        status, out, _ = self.request('POST', '/api/playlists',
                                      dict(body, scope='user', rev=rev), cookie=cookie)
        self.assertEqual(status, 200, out)
        return out

    def make_playlist(self, cookie, name, dirs=('song_a',)):
        mine = self.own_only(cookie)
        mine[name] = list(dirs)
        return self.own(cookie, {'playlists': mine})

    def make_link(self, cookie, name, role):
        status, d, _ = self.request('POST', '/api/share-links',
                                    {'name': name, 'role': role}, cookie=cookie)
        self.assertEqual(status, 200, d)
        return d['token']

    def claim(self, cookie, token):
        return self.request('POST', '/api/share-links/claim', {'token': token},
                            cookie=cookie)

    def share_write(self, cookie, playlists, owner='alice'):
        status, d, _ = self.request('POST', '/api/playlists',
                                    {'playlists': playlists, 'scope': 'share',
                                     'owner': owner, 'rev': self.playlists(cookie)['rev']},
                                    cookie=cookie)
        return status, d

    # -- the flow ----------------------------------------------------------

    def test_01_edit_link_claim_and_collaborate(self):
        alice = self.login_cookie('alice', ALICE)
        bob = self.login_cookie('bob', 'bobpass123')
        self.make_playlist(alice, 'Medley', ['song_a'])
        token = self.make_link(alice, 'Medley', 'edit')

        status, d, _ = self.claim(bob, token)
        self.assertEqual(status, 200, d)
        self.assertEqual(d['claimed'], {'owner': 'alice', 'name': 'Medley', 'role': 'edit'})
        self.assertEqual(d['mine']['Medley'], ['song_a'])
        self.assertEqual(d['sharedMeta']['Medley'], {'owner': 'alice', 'role': 'edit'})

        status, d = self.share_write(bob, {'Medley': ['song_b']})
        self.assertEqual(status, 200, d)
        self.assertEqual(self.playlists(alice)['mine']['Medley'], ['song_b'],
                         'a collaborator writes into the owner\'s bucket')

    def test_02_view_link_is_read_only(self):
        alice = self.login_cookie('alice', ALICE)
        carol = self.login_cookie('carol', 'carolpass123')
        self.make_playlist(alice, 'WatchOnly', ['song_a'])
        self.claim(carol, self.make_link(alice, 'WatchOnly', 'view'))

        status, d = self.share_write(carol, {'WatchOnly': ['song_z']})
        self.assertEqual(status, 403, d)
        for path, body in (('/api/clips', {'key': 'WatchOnly::song_a',
                                           'clip': {'start': 1, 'end': 9}}),
                           ('/api/presets', {'key': 'WatchOnly::song_a',
                                             'setup': {'tag': 'mine'}})):
            status, d, _ = self.request('POST', path,
                                        dict(body, scope='share', owner='alice'),
                                        cookie=carol)
            self.assertEqual(status, 403, d)
        self.assertEqual(self.playlists(alice)['mine']['WatchOnly'], ['song_a'])

    def test_03_revoke_stops_new_claims_but_keeps_grants(self):
        alice = self.login_cookie('alice', ALICE)
        carol = self.login_cookie('carol', 'carolpass123')
        dave = self.login_cookie('dave', 'davepass123')
        self.make_playlist(alice, 'Revocable', ['song_a'])
        token = self.make_link(alice, 'Revocable', 'view')
        self.assertEqual(self.claim(carol, token)[0], 200)

        status, d, _ = self.request('POST', '/api/share-links',
                                    {'token': token, 'revoke': True}, cookie=alice)
        self.assertEqual(status, 200, d)
        self.assertNotIn(token, d.get('myLinks') or {})
        self.assertEqual(self.claim(dave, token)[0], 404,
                         'a revoked link stops new claims')
        self.assertIn('Revocable', self.playlists(carol)['sharedMeta'],
                      'but a claim already made stands')

    def test_04_remove_a_person_and_leave(self):
        alice = self.login_cookie('alice', ALICE)
        bob = self.login_cookie('bob', 'bobpass123')
        self.make_playlist(alice, 'Panel', ['song_a'])
        token = self.make_link(alice, 'Panel', 'view')
        self.claim(bob, token)

        status, d, _ = self.request('POST', '/api/shares',
                                    {'name': 'Panel', 'user': 'bob', 'role': None},
                                    cookie=alice)
        self.assertEqual(status, 200, d)
        self.assertNotIn('Panel', self.playlists(bob)['sharedMeta'])
        self.claim(bob, token)          # the link still works; the person was removed
        self.assertIn('Panel', self.playlists(bob)['sharedMeta'])

        status, d, _ = self.request('POST', '/api/shares',
                                    {'name': 'Panel', 'owner': 'alice', 'leave': True},
                                    cookie=bob)
        self.assertEqual(status, 200, d)
        self.assertNotIn('Panel', self.playlists(bob)['sharedMeta'])
        self.assertEqual(self.playlists(alice)['mine']['Panel'], ['song_a'],
                         'leaving never touches the owner\'s copy')

    def test_05_owner_delete_prunes_shares_and_links(self):
        alice = self.login_cookie('alice', ALICE)
        bob = self.login_cookie('bob', 'bobpass123')
        carol = self.login_cookie('carol', 'carolpass123')
        self.make_playlist(alice, 'Temp', ['song_a'])
        token = self.make_link(alice, 'Temp', 'edit')
        self.claim(bob, token)

        remaining = {n: v for n, v in self.own_only(alice).items() if n != 'Temp'}
        self.own(alice, {'playlists': remaining})

        self.assertNotIn('Temp', self.playlists(bob)['sharedMeta'])
        self.assertNotIn('Temp', self.playlists(alice).get('myShares') or {})
        self.assertEqual(self.claim(carol, token)[0], 404)
        status, d = self.share_write(bob, {'Temp': ['song_a']})
        self.assertEqual(status, 404, d)

    def test_06_shares_survive_the_owners_whole_map_save(self):
        alice = self.login_cookie('alice', ALICE)
        carol = self.login_cookie('carol', 'carolpass123')
        self.make_playlist(alice, 'Keep', ['song_a'])
        self.claim(carol, self.make_link(alice, 'Keep', 'view'))

        # An ordinary save of Alice's own map: the write that used to rebuild
        # playlists.json from a literal, and would have dropped `shares`.
        self.make_playlist(alice, 'Another', ['song_b'])
        with open(os.path.join(self.tmp, 'playlists.json'), encoding='utf-8') as f:
            raw = json.load(f)
        self.assertEqual(raw['shares']['carol']['alice']['Keep'], 'view')
        self.assertTrue(raw.get('shareLinks'), 'link records must survive too')
        self.assertIn('Keep', self.playlists(carol)['sharedMeta'])

    def test_07_own_playlist_shadows_a_share(self):
        alice = self.login_cookie('alice', ALICE)
        bob = self.login_cookie('bob', 'bobpass123')
        self.make_playlist(bob, 'Twin', ['song_bob'])
        self.make_playlist(alice, 'Twin', ['song_alice'])
        self.claim(bob, self.make_link(alice, 'Twin', 'view'))

        d = self.playlists(bob)
        self.assertEqual(d['mine']['Twin'], ['song_bob'], 'own wins')
        self.assertNotIn('Twin', d['sharedMeta'])
        self.assertEqual(d['shadowed'], [{'name': 'Twin', 'owner': 'alice', 'role': 'view'}])

        self.own(bob, {'playlists': {}})        # deleting his own un-shadows it
        d = self.playlists(bob)
        self.assertEqual(d['mine']['Twin'], ['song_alice'])
        self.assertEqual(d['sharedMeta']['Twin']['owner'], 'alice')

    def test_08_viewer_login_with_an_edit_link(self):
        alice = self.login_cookie('alice', ALICE)
        dave = self.login_cookie('dave', 'davepass123')
        self.make_playlist(alice, 'ForDave', ['song_a'])
        self.claim(dave, self.make_link(alice, 'ForDave', 'edit'))

        # The link lets a viewer-role login write EXACTLY that playlist...
        status, d = self.share_write(dave, {'ForDave': ['song_c']})
        self.assertEqual(status, 200, d)
        self.assertEqual(self.playlists(alice)['mine']['ForDave'], ['song_c'])

        # ...and nothing else: not a bucket of their own, not the shared set.
        rev = d['rev']
        status, d, _ = self.request('POST', '/api/playlists',
                                    {'playlists': {'Mine': []}, 'scope': 'user', 'rev': rev},
                                    cookie=dave)
        self.assertEqual(status, 403, d)
        status, d, _ = self.request('POST', '/api/playlists',
                                    {'playlists': {'Theirs': []}, 'scope': 'shared', 'rev': rev},
                                    cookie=dave)
        self.assertEqual(status, 403, d)

    def test_09_clips_and_mixes_land_in_the_owner_bucket(self):
        alice = self.login_cookie('alice', ALICE)
        carol = self.login_cookie('carol', 'carolpass123')
        self.make_playlist(alice, 'Shared', ['song_a'])
        self.claim(carol, self.make_link(alice, 'Shared', 'edit'))

        status, d, _ = self.request('POST', '/api/clips',
                                    {'key': 'Shared::song_a', 'clip': {'start': 1.5, 'end': 30.0},
                                     'scope': 'share', 'owner': 'alice'}, cookie=carol)
        self.assertEqual(status, 200, d)
        status, d, _ = self.request('POST', '/api/presets',
                                    {'key': 'Shared::*', 'setup': {'preset': 'karaoke'},
                                     'scope': 'share', 'owner': 'alice'}, cookie=carol)
        self.assertEqual(status, 200, d)

        for who in (alice, carol):
            status, d, _ = self.request('GET', '/api/clips', cookie=who)
            self.assertEqual(d['mine']['Shared::song_a'], {'start': 1.5, 'end': 30.0})
            status, d, _ = self.request('GET', '/api/presets', cookie=who)
            self.assertEqual(d['mine']['Shared::*']['preset'], 'karaoke')

        with open(os.path.join(self.tmp, 'clips.json'), encoding='utf-8') as f:
            raw = json.load(f)
        self.assertIn('alice', raw.get('__user__') or {})
        self.assertNotIn('carol', raw.get('__user__') or {},
                         'the collaborator\'s own bucket stays empty')

    def test_10_concurrent_links_under_the_lock(self):
        import concurrent.futures as cf
        alice = self.login_cookie('alice', ALICE)
        names = ['C%d' % i for i in range(8)]
        mine = self.own_only(alice)
        mine.update({n: ['song_a'] for n in names})
        self.own(alice, {'playlists': mine})

        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(lambda n: self.request(
                'POST', '/api/share-links', {'name': n, 'role': 'view'}, cookie=alice), names))
        self.assertTrue(all(r[0] == 200 for r in results), results)
        with open(os.path.join(self.tmp, 'playlists.json'), encoding='utf-8') as f:
            raw = json.load(f)
        made = {r['name'] for r in (raw.get('shareLinks') or {}).values()}
        self.assertTrue(set(names) <= made,
                        'every concurrent grant must survive the read-modify-write')


class Live(ServiceCase):
    """Live lyrics: the host publishes, anyone with the code follows, only the
    broadcast song's lyrics are reachable, and a viewer cannot publish."""

    seed_accounts = {
        'host': ('hostpass123', 'editor'),
        'dave': ('davepass123', 'viewer'),      # a viewer-role login, as `beatz` is
    }

    SONG = 'Aa_Chal_Ke_Tujhe'

    def publish(self, cookie, **over):
        body = {'dir': self.SONG, 'title': 'Aa Chal Ke Tujhe', 'pos': 41.5,
                'playing': True, 'tempo': 1}
        body.update(over)
        return self.request('POST', '/api/live', body, cookie=cookie)

    def test_01_publish_then_follow_anonymously(self):
        host = self.login_cookie('host', 'hostpass123')
        status, d, _ = self.publish(host)
        self.assertEqual(status, 200, d)
        code = d['code']
        self.assertGreaterEqual(len(code), 8, 'the code is the whole credential')

        # No cookie, no X-Beatz-User: exactly what a follower in a park has.
        status, s, _ = self.request('GET', '/api/live/' + code)
        self.assertEqual(status, 200, s)
        self.assertEqual(s['dir'], self.SONG)
        self.assertEqual(s['title'], 'Aa Chal Ke Tujhe')
        self.assertAlmostEqual(s['pos'], 41.5, places=2)
        self.assertTrue(s['playing'])
        self.assertEqual(s['tempo'], 1)
        self.assertLess(s['age'], 5000, 'age lets the follower extrapolate')

    def test_02_only_the_broadcast_song_is_reachable(self):
        host = self.login_cookie('host', 'hostpass123')
        status, d, _ = self.publish(host, pos=0, playing=False)
        code = d['code']
        status, lyrics, _ = self.request('GET', '/api/live/%s/lyrics' % code)
        self.assertEqual(status, 200)
        self.assertIsInstance(lyrics, list)
        self.assertTrue(lyrics and 'start' in lyrics[0] and 'text' in lyrics[0],
                        'the same shape the player parses')

        # A song with no timed lyrics answers 404, so the follower can say so.
        status, d, _ = self.publish(host, dir='Fanna', title='Fanna', code=code)
        self.assertEqual(status, 200, d)
        self.assertEqual(d['code'], code, 'the same session keeps its code')
        status, nothing, _ = self.request('GET', '/api/live/%s/lyrics' % code)
        self.assertEqual(status, 404)

        for path in ('/api/live/nosuchcode', '/api/live/nosuchcode/lyrics'):
            status, _, _ = self.request('GET', path)
            self.assertEqual(status, 404, path)

    def test_03_a_viewer_cannot_publish_and_nobody_sees_the_session_list(self):
        dave = self.login_cookie('dave', 'davepass123')
        status, d, _ = self.publish(dave)
        self.assertEqual(status, 403, d)

        # Anonymous publish is refused the same way, and there is no way to
        # list sessions: the code is the credential.
        status, d, _ = self.request('POST', '/api/live',
                                    {'dir': self.SONG, 'title': 'x', 'pos': 0,
                                     'playing': False, 'tempo': 1})
        self.assertEqual(status, 403, d)
        status, d, _ = self.request('GET', '/api/live')
        self.assertEqual(status, 404, d)

    def test_04_stop_ends_the_session_and_a_new_one_gets_a_new_code(self):
        host = self.login_cookie('host', 'hostpass123')
        status, d, _ = self.publish(host)
        first = d['code']
        status, d, _ = self.request('POST', '/api/live/stop', {}, cookie=host)
        self.assertEqual(status, 200, d)
        self.assertEqual(self.request('GET', '/api/live/' + first)[0], 404)

        status, d, _ = self.publish(host)
        self.assertNotEqual(d['code'], first)

    def test_05_bad_input_is_refused(self):
        host = self.login_cookie('host', 'hostpass123')
        for body in ({'dir': '../etc', 'pos': 0},
                     {'dir': 'a b', 'pos': 0},
                     {'dir': self.SONG, 'pos': 'nonsense'}):
            status, d, _ = self.request('POST', '/api/live',
                                        dict({'title': '', 'playing': False, 'tempo': 1}, **body),
                                        cookie=host)
            self.assertEqual(status, 400, (body, d))


class PublicDoor(ServiceCase):
    """What an ANONYMOUS visitor may do once the site is reachable without the
    Caddy password (the 30 Sep rollout). Reading and the live lyrics page are
    open -- that is the point of a link you can send anybody -- while the three
    endpoints whose output the laptop then ACTS on need a login, or the public
    internet can fill the download queue."""

    seed_accounts = {'fan': ('fanpass123', 'editor')}

    def test_01_anonymous_writes_that_feed_the_pipeline_are_refused(self):
        for path, body in (('/api/request', {'song': 'Kesariya'}),
                           ('/api/report', {'dir': 'Kesariya', 'reason': 'wrong-song'}),
                           ('/api/lyrics', {'dir': 'Kesariya', 'lyrics': 'a\nb\nc\nd\n'})):
            status, d, _ = self.request('POST', path, body)
            self.assertEqual(status, 403, (path, d))

    def test_02_anonymous_cannot_mint_a_library_token(self):
        status, d, _ = self.request('GET', '/api/stem-token')
        self.assertEqual(status, 403, d)
        # Signed in, the same call gets past the login check and fails on the
        # missing key file instead -- 503, not 403. That difference is the
        # whole assertion.
        cookie = self.login_cookie('fan', 'fanpass123')
        status, d, _ = self.request('GET', '/api/stem-token', cookie=cookie)
        self.assertEqual(status, 503, d)

    def test_03_signed_in_writes_still_work(self):
        cookie = self.login_cookie('fan', 'fanpass123')
        status, d, _ = self.request('POST', '/api/report',
                                    {'dir': 'Kesariya', 'reason': 'wrong-song'}, cookie=cookie)
        self.assertEqual(status, 200, d)
        status, d, _ = self.request('POST', '/api/request',
                                    {'song': 'Kesariya'}, cookie=cookie)
        self.assertEqual(status, 200, d)

    def test_04_a_name_that_is_not_a_login_is_no_name(self):
        """Caddy sends its unresolved placeholder as the user header once
        basic_auth stops matching /api/*. It is truthy, so it must be rejected
        by SHAPE -- this is the bug that let anonymous visitors mint library
        tokens for a few minutes on 30 Sep."""
        import importlib.util
        spec = importlib.util.spec_from_file_location('beatz_qs', SERVICE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for junk in ('{http.auth.user.id}', ' ', 'a b', 'x' * 41, 'naïve'):
            self.assertFalse(mod.valid_login(junk), junk)
        for good in ('iti', 'karan', 'beatz', 'TestIJ_2'):
            self.assertTrue(mod.valid_login(good), good)

    def test_05_reading_stays_open(self):
        for path in ('/api/health', '/api/playlists', '/api/clips', '/api/presets'):
            status, d, _ = self.request('GET', path)
            self.assertEqual(status, 200, (path, d))


if __name__ == '__main__':
    unittest.main(verbosity=2)
