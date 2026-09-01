/* BeatznBox service worker.
 *
 * Exists for one reason: at a jam session the phone is on someone's guest wifi,
 * and a cold song costs 20 seconds because 24MB has to come down first. A song
 * the phone already holds loads in about 2. This makes "already holds" something
 * you can arrange in advance instead of something you hope Chrome remembered --
 * measured on the OnePlus, Chrome was quietly evicting songs mid-session.
 *
 * Two caches, two policies, and the split matters:
 *
 *   stems  -- cache FIRST. A stem file never changes: publishing new audio for a
 *             song writes a new directory, and re-encoding would be a deliberate
 *             cache-version bump. So a hit is always correct and never touches
 *             the network.
 *   shell  -- network FIRST, cache only as fallback. index.html changes on every
 *             deploy. Cache-first here would pin every phone to whatever version
 *             it saw first, and no amount of deploying would move it -- the
 *             classic way a service worker turns into a bug you cannot ship past.
 *
 * Escape hatch: loading any page with ?nosw=1 unregisters this worker and drops
 * its caches. Outside testers have this link, and a service worker that goes
 * wrong is not something they could clear themselves.
 */

const VERSION = 'v1';
const SHELL_CACHE = `beatz-shell-${VERSION}`;
const STEM_CACHE = `beatz-stems-${VERSION}`;   // bump only if the audio is re-encoded
const SHELL_URLS = ['./', './index.html', './tempo-worklet.js'];

self.addEventListener('install', (e) => {
    // addAll fails atomically on any miss; the shell must not block install.
    e.waitUntil(caches.open(SHELL_CACHE).then((c) =>
        Promise.allSettled(SHELL_URLS.map((u) => c.add(u)))
    ).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
    e.waitUntil((async () => {
        // Drop caches from older versions, but never the current stem cache --
        // that is the user's downloaded library and re-fetching it is the exact
        // 20 seconds a song this is meant to avoid.
        const keep = new Set([SHELL_CACHE, STEM_CACHE]);
        for (const k of await caches.keys()) {
            if (k.startsWith('beatz-') && !keep.has(k)) await caches.delete(k);
        }
        await self.clients.claim();
    })());
});

const isStem = (url) =>
    url.pathname.includes('/stems/') && /\.(mp3|json|txt)$/.test(url.pathname)
    && !url.pathname.endsWith('/songs.json');   // the manifest changes; never pin it

self.addEventListener('fetch', (e) => {
    const req = e.request;
    if (req.method !== 'GET') return;
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

    if (isStem(url)) {
        e.respondWith((async () => {
            const hit = await caches.match(req, { cacheName: STEM_CACHE });
            if (hit) return hit;
            const resp = await fetch(req);
            // Only 200s are worth keeping. A 401 from an expired session cached
            // here would lock the app out until the cache was cleared by hand.
            if (resp.ok) {
                const c = await caches.open(STEM_CACHE);
                c.put(req, resp.clone());
            }
            return resp;
        })());
        return;
    }

    e.respondWith((async () => {
        try {
            const resp = await fetch(req);
            if (resp.ok && SHELL_URLS.some((u) => url.pathname.endsWith(u.replace('./', '')))) {
                const c = await caches.open(SHELL_CACHE);
                c.put(req, resp.clone());
            }
            return resp;
        } catch (err) {
            const hit = await caches.match(req, { cacheName: SHELL_CACHE });
            if (hit) return hit;
            throw err;
        }
    })());
});

// The page drives downloading, because only it knows which songs the user picked
// and only it can show progress. The worker just reports what is already held.
self.addEventListener('message', (e) => {
    if (e.data && e.data.type === 'CLEAR_STEMS') {
        e.waitUntil(caches.delete(STEM_CACHE).then(() =>
            e.source && e.source.postMessage({ type: 'STEMS_CLEARED' })));
    }
});
