/* Serves BeatznBox stems from R2, behind the same password as the site.
 *
 * Why this exists: the origin is in Nuremberg and everyone using this is in
 * Asia. Measured from the phone, median RTT is 305ms to Nuremberg against
 * 120ms to Cloudflare's nearest edge, and 83-89% of a cold song's load time is
 * the download. Serving the audio from the edge removes that distance without
 * touching the files or the decode.
 *
 * Why it checks a password rather than making the bucket public: the Caddyfile
 * is explicit that the login exists because "running a server other people
 * download songs from is distribution". A public bucket would hand the whole
 * library to anyone with a URL. The bucket stays private and this is the only
 * way in.
 *
 * It must run on the SAME hostname as the player. Browsers only attach an
 * Authorization header automatically to the origin that asked for it, so a
 * separate stems.* domain would mean the page holding the password and the
 * request needing it are on different origins -- and the player has no copy of
 * the password to send explicitly. Same origin, and it just works with no
 * change to the player at all.
 */

const REALM = 'BeatznBox';

/** Compare without leaking the answer through timing. */
function sameSecret(a, b) {
    if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
    let diff = 0;
    for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return diff === 0;
}

function authorised(request, env) {
    // Fail CLOSED when the password is missing. The first version fell back to
    // `env.BEATZ_PASS || ''`, which compared the supplied password against the
    // empty string -- and empty equals empty, so an unconfigured Worker
    // authorised anybody sending "beatz:". Deployed alongside a public
    // workers.dev URL that is an open door to the whole library. A Worker with
    // no password configured must serve nobody, not everybody.
    const expected = env.BEATZ_PASS;
    if (typeof expected !== 'string' || expected.length === 0) return false;

    const header = request.headers.get('Authorization') || '';
    if (!header.startsWith('Basic ')) return false;
    let decoded;
    try {
        decoded = atob(header.slice(6));
    } catch (e) {
        return false;                     // not valid base64
    }
    const at = decoded.indexOf(':');      // a password may itself contain ':'
    if (at < 0) return false;
    return sameSecret(decoded.slice(0, at), env.BEATZ_USER || 'beatz')
        && sameSecret(decoded.slice(at + 1), expected);
}

const deny = () => new Response('Unauthorized', {
    status: 401,
    headers: { 'WWW-Authenticate': `Basic realm="${REALM}"`, 'Cache-Control': 'no-store' },
});

export default {
    async fetch(request, env) {
        if (request.method !== 'GET' && request.method !== 'HEAD') {
            return new Response('Method not allowed', { status: 405 });
        }
        if (!authorised(request, env)) return deny();

        const url = new URL(request.url);
        // /stems/Kesariya/vocals.mp3 -> Kesariya/vocals.mp3
        const key = decodeURIComponent(url.pathname.replace(/^\/stems\/+/, ''));
        if (!key || key.includes('..')) return new Response('Not found', { status: 404 });

        // Range matters for audio even though the player fetches whole files:
        // a browser media element will ask for one, and answering 200 to a
        // Range request makes seeking silently broken.
        const range = request.headers.get('Range');
        const object = await env.STEMS.get(key, range ? { range: request.headers } : undefined);
        if (object === null) return new Response('Not found', { status: 404 });

        const headers = new Headers();
        object.writeHttpMetadata(headers);
        headers.set('etag', object.httpEtag);
        // A stem never changes -- new audio for a song writes a new directory --
        // so this is safe to hold for a long time.
        headers.set('Cache-Control', 'public, max-age=604800');
        headers.set('Accept-Ranges', 'bytes');
        // Private content: never let a shared cache hold it for another user.
        headers.append('Vary', 'Authorization');

        if (object.range && range) {
            const end = object.range.offset + object.range.length - 1;
            headers.set('Content-Range',
                `bytes ${object.range.offset}-${end}/${object.size}`);
            return new Response(object.body, { status: 206, headers });
        }
        return new Response(request.method === 'HEAD' ? null : object.body, { headers });
    },
};
