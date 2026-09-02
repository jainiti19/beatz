/* Exercises the Worker's authorisation without deploying it.
 *
 * This file exists because the previous Worker could not be tested at all: it
 * checked the site's basic-auth password, which the person writing it did not
 * have, so the success path could only ever run in production -- and it broke
 * the live site twice. A signed token can be minted from the key, so "a valid
 * credential is accepted" is finally a thing a test can assert.
 *
 * R2 is stubbed. What is under test is the auth and the routing, not
 * Cloudflare's storage.
 *
 * Run: node server/r2-worker/test/auth.test.mjs
 */
import worker from '../src/index.js';

const KEY = 'a'.repeat(64);
const ORIGIN = 'https://beatznbox.wesimplyhome.com';

function b64url(buf) {
    return Buffer.from(buf).toString('base64')
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
async function mint(exp, key = KEY) {
    const k = await crypto.subtle.importKey('raw', new TextEncoder().encode(key),
        { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const msg = `v1.${exp}`;
    return `${msg}.${b64url(await crypto.subtle.sign('HMAC', k, new TextEncoder().encode(msg)))}`;
}
const soon = () => Math.floor(Date.now() / 1000) + 3600;
const past = () => Math.floor(Date.now() / 1000) - 60;

const BODY = Buffer.from('fake-mp3-bytes-for-the-test');
const env = {
    STEM_TOKEN_KEY: KEY,
    STEMS: {
        async get(key, opts) {
            if (key !== 'Kesariya/vocals.mp3') return null;
            if (opts && opts.range) {
                return { body: BODY.subarray(0, 5), size: BODY.length,
                         range: { offset: 0, length: 5 },
                         httpEtag: '"e"', writeHttpMetadata() {} };
            }
            return { body: BODY, size: BODY.length, httpEtag: '"e"',
                     writeHttpMetadata(h) { h.set('Content-Type', 'audio/mpeg'); } };
        },
        async list({ prefix = '', limit = 20 }) {
            const all = [{ key: 'Kesariya/vocals.mp3', size: 100 }];
            return { truncated: false, objects: all.filter((o) => o.key.startsWith(prefix)).slice(0, limit) };
        },
    },
};

const url = (p, t) => `https://stems.example${p}` + (t === undefined ? '' : `?t=${encodeURIComponent(t)}`);
const call = (u, init = {}) => worker.fetch(new Request(u, init), env);

let failed = 0;
async function check(name, fn) {
    try { await fn(); console.log(`  ok    ${name}`); }
    catch (e) { failed++; console.log(`  FAIL  ${name}\n        ${e.message}`); }
}
const eq = (a, b, what) => { if (a !== b) throw new Error(`${what}: got ${a}, want ${b}`); };

const STEM = '/stems/Kesariya/vocals.mp3';

console.log('token');
await check('a valid token is accepted', async () => {
    const r = await call(url(STEM, await mint(soon())));
    eq(r.status, 200, 'status');
    eq(r.headers.get('X-Beatz-Served-By'), 'r2-worker', 'marker');
});
await check('no token is refused', async () => eq((await call(url(STEM))).status, 401, 'status'));
await check('an empty token is refused', async () => eq((await call(url(STEM, ''))).status, 401, 'status'));
await check('a malformed token is refused', async () => eq((await call(url(STEM, 'garbage'))).status, 401, 'status'));
await check('a token signed with another key is refused', async () => {
    eq((await call(url(STEM, await mint(soon(), 'b'.repeat(64))))).status, 401, 'status');
});
await check('a tampered expiry is refused', async () => {
    const t = await mint(soon());
    const forged = t.replace(/^v1\.\d+/, `v1.${soon() + 99999}`);
    eq((await call(url(STEM, forged))).status, 401, 'status');
});
await check('an expired token is refused', async () => {
    eq((await call(url(STEM, await mint(past())))).status, 401, 'status');
});
await check('a Worker with no key configured serves NOBODY', async () => {
    const r = await worker.fetch(new Request(url(STEM, await mint(soon()))), { ...env, STEM_TOKEN_KEY: '' });
    eq(r.status, 401, 'status');
});
await check('a 401 never asks the browser for a password', async () => {
    const r = await call(url(STEM));
    eq(r.headers.get('WWW-Authenticate'), null, 'WWW-Authenticate');
});

console.log('routing');
await check('an unknown key is 404, not 401', async () => {
    eq((await call(url('/stems/Nope/vocals.mp3', await mint(soon())))).status, 404, 'status');
});
await check('path traversal is refused', async () => {
    eq((await call(url('/stems/../secret', await mint(soon())))).status, 404, 'status');
});
await check('POST is refused', async () => {
    eq((await call(url(STEM, await mint(soon())), { method: 'POST' })).status, 405, 'status');
});
await check('a Range request answers 206, not 200', async () => {
    const r = await call(url(STEM, await mint(soon())), { headers: { Range: 'bytes=0-4' } });
    eq(r.status, 206, 'status');
    eq(r.headers.get('Content-Range'), `bytes 0-4/${BODY.length}`, 'Content-Range');
});
await check('the key listing needs a token too', async () => {
    eq((await call(url('/_keys'))).status, 401, 'status');
    eq((await call(url('/_keys', await mint(soon())))).status, 200, 'status');
});

console.log('cors');
await check('the player origin is allowed', async () => {
    const r = await call(url(STEM, await mint(soon())), { headers: { Origin: ORIGIN } });
    eq(r.headers.get('Access-Control-Allow-Origin'), ORIGIN, 'ACAO');
    eq(r.headers.get('Vary'), 'Origin', 'Vary');
});
await check('an unknown origin gets no CORS grant', async () => {
    const r = await call(url(STEM, await mint(soon())), { headers: { Origin: 'https://evil.example' } });
    eq(r.headers.get('Access-Control-Allow-Origin'), null, 'ACAO');
});
await check('preflight allows Range, so seeking cannot break silently', async () => {
    const r = await call(url(STEM), { method: 'OPTIONS', headers: { Origin: ORIGIN } });
    eq(r.status, 204, 'status');
    eq(r.headers.get('Access-Control-Allow-Headers'), 'Range', 'allow-headers');
});

console.log(failed ? `\n${failed} FAILED` : '\nall passed');
process.exit(failed ? 1 : 0);
