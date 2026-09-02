/* Serves BeatznBox stems from R2, authorised by a signed token.
 *
 * Why this exists: the origin is in Nuremberg and everyone using this is in
 * Asia. Measured from the phone, median RTT is 305ms to Nuremberg against
 * 120ms to Cloudflare's nearest edge, and 83-89% of a cold song's load time is
 * the download.
 *
 * Why it is not a public bucket: the Caddyfile is explicit that the login
 * exists because "running a server other people download songs from is
 * distribution". The bucket stays private and this is the only way in.
 *
 * WHY A TOKEN AND NOT THE SITE PASSWORD -- this is the whole design, and the
 * previous version got it wrong three separate ways:
 *
 *  1. Checking basic auth forced this onto the player's OWN hostname, because
 *     a browser only sends an Authorization header to the origin that asked
 *     for it. So switching it on meant putting a Worker route in front of the
 *     live site, and when it was wrong the live site was wrong. It was wrong
 *     twice on 2 Sep. With a token in the URL there is no such constraint:
 *     this runs on its own hostname and the player is untouchable from here.
 *  2. Browsers key credentials by (origin, realm). Announcing a realm that did
 *     not match Caddy's meant the browser never offered the password it held
 *     and every stem 401'd. There is no realm here to get wrong.
 *  3. Nobody could test it. The success path needed the site password, which
 *     the person writing this does not have -- so it could only ever be
 *     exercised in production, on someone else's phone. A token is mintable
 *     from the shared key, so the success path is testable from a laptop.
 *
 * The token is issued by GET /api/stem-token on the queue service, which sits
 * behind Caddy's basic auth -- so only someone already logged in can get one.
 * It says nothing but "issued, and valid until": the authority it grants is
 * exactly the authority the logged-in user already has.
 */

const TOKEN_PREFIX = 'v1';

// Origins allowed to read the audio from a page. Not a security boundary --
// the token is that -- but it stops the library being hotlinked from anywhere.
const ALLOWED_ORIGINS = [
    'https://beatznbox.wesimplyhome.com',
    'https://bnb.thegoodruckus.com',
];

function corsHeaders(request) {
    const origin = request.headers.get('Origin');
    const h = new Headers();
    if (origin && ALLOWED_ORIGINS.includes(origin)) {
        h.set('Access-Control-Allow-Origin', origin);
        // The allowlist means the response genuinely differs per origin, and a
        // shared cache that missed this would hand one origin another's copy.
        h.set('Vary', 'Origin');
        h.set('Access-Control-Expose-Headers', 'Content-Length, Content-Range, X-Beatz-Served-By');
    }
    return h;
}

/** Compare without leaking the answer through timing. */
function sameSecret(a, b) {
    if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
    let diff = 0;
    for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return diff === 0;
}

function b64url(bytes) {
    let s = '';
    for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function sign(key, message) {
    const k = await crypto.subtle.importKey(
        'raw', new TextEncoder().encode(key),
        { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    return b64url(await crypto.subtle.sign('HMAC', k, new TextEncoder().encode(message)));
}

/** null when good, else a short reason -- the reason is logged, never returned. */
async function tokenProblem(token, env) {
    // Fail CLOSED when the key is missing. An earlier version of this Worker
    // compared the supplied password against `env.BEATZ_PASS || ''`, and empty
    // equals empty, so an unconfigured Worker authorised everybody. A Worker
    // with no key configured must serve nobody.
    const key = env.STEM_TOKEN_KEY;
    if (typeof key !== 'string' || key.length === 0) return 'no key configured';
    if (!token) return 'no token';

    const parts = token.split('.');
    if (parts.length !== 3 || parts[0] !== TOKEN_PREFIX) return 'malformed';
    const [, exp, sig] = parts;
    if (!/^\d+$/.test(exp)) return 'malformed exp';
    // Expiry is checked BEFORE the signature is trusted, but only after the
    // shape is known -- an expired token that we signed is still a forgery
    // risk if the clock claim is taken on faith, so verify both.
    const expected = await sign(key, `${TOKEN_PREFIX}.${exp}`);
    if (!sameSecret(sig, expected)) return 'bad signature';
    if (Number(exp) * 1000 < Date.now()) return 'expired';
    return null;
}

const deny = (request) => new Response('Unauthorized', {
    status: 401,
    headers: (() => {
        const h = corsHeaders(request);
        h.set('Cache-Control', 'no-store');
        h.set('Content-Type', 'text/plain');
        // Deliberately NO WWW-Authenticate. This Worker is on its own
        // hostname and must never make a browser open a Sign in dialog: a
        // service worker producing a 401 is what locked a user out of the
        // live site, and a 401 that prompts is how that happened.
        return h;
    })(),
});

export default {
    async fetch(request, env) {
        if (request.method === 'OPTIONS') {
            const h = corsHeaders(request);
            h.set('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS');
            // Range is not a CORS-safelisted request header, so a media element
            // asking for one would preflight. The player uses fetch() and does
            // not, but answering costs nothing and seeking would break silently.
            h.set('Access-Control-Allow-Headers', 'Range');
            h.set('Access-Control-Max-Age', '86400');
            return new Response(null, { status: 204, headers: h });
        }
        if (request.method !== 'GET' && request.method !== 'HEAD') {
            return new Response('Method not allowed', { status: 405 });
        }

        const url = new URL(request.url);
        const problem = await tokenProblem(url.searchParams.get('t'), env);
        if (problem) {
            console.log(`denied: ${problem} for ${url.pathname}`);
            return deny(request);
        }

        /* Token-protected key listing. Kept because the bucket was filled by
         * hand and nothing in the repo recorded the key layout, so verifying
         * "is the file actually there" meant guessing paths one at a time.
         * Reveals names, never bytes, and needs the same token as the audio. */
        if (url.pathname === '/_keys') {
            // Paged. R2 caps a list at 1000 and this library is already 651
            // objects; a caller that ignored the cursor would silently see a
            // prefix of the bucket and conclude files were missing. Two
            // separate bugs in this project have been exactly that shape.
            const listed = await env.STEMS.list({
                prefix: url.searchParams.get('prefix') || '',
                limit: Math.min(Number(url.searchParams.get('limit')) || 20, 1000),
                cursor: url.searchParams.get('cursor') || undefined,
            });
            const h = corsHeaders(request);
            h.set('Content-Type', 'application/json');
            h.set('Cache-Control', 'no-store');
            return new Response(JSON.stringify({
                truncated: listed.truncated,
                cursor: listed.truncated ? listed.cursor : null,
                keys: listed.objects.map((o) => ({ key: o.key, size: o.size })),
            }, null, 1), { headers: h });
        }

        // /stems/Kesariya/vocals.mp3 -> Kesariya/vocals.mp3
        const key = decodeURIComponent(url.pathname.replace(/^\/stems\/+/, ''));
        if (!key || key.includes('..')) return new Response('Not found', { status: 404 });

        // Range matters for audio even though the player fetches whole files:
        // a browser media element will ask for one, and answering 200 to a
        // Range request makes seeking silently broken.
        const range = request.headers.get('Range');
        const object = await env.STEMS.get(key, range ? { range: request.headers } : undefined);
        if (object === null) {
            const h = corsHeaders(request);
            return new Response('Not found', { status: 404, headers: h });
        }

        const headers = corsHeaders(request);
        object.writeHttpMetadata(headers);
        headers.set('etag', object.httpEtag);
        // The player's URLs carry ?v=<mp3 mtime>, so a reprocessed song is a
        // different URL and this can be held for a long time without pinning
        // stale audio -- which is what stopped Caddy using `immutable`.
        headers.set('Cache-Control', 'public, max-age=604800');
        headers.set('Accept-Ranges', 'bytes');
        // Both Caddy and this send the same cache headers, so without a marker
        // there is no way to tell from a response which one answered -- and
        // "is it actually using R2?" is the whole question here.
        headers.set('X-Beatz-Served-By', 'r2-worker');

        if (object.range && range) {
            const end = object.range.offset + object.range.length - 1;
            headers.set('Content-Range', `bytes ${object.range.offset}-${end}/${object.size}`);
            return new Response(object.body, { status: 206, headers });
        }
        return new Response(request.method === 'HEAD' ? null : object.body, { headers });
    },
};
