/* Self-uninstalling stub. Deliberately NOT a cache.
 *
 * The offline feature this replaced sat in front of every request the app
 * made. The site is behind basic auth and a service worker's own fetches do
 * not carry the user's credentials, so those requests came back 401 -- and a
 * browser answers a 401 by re-opening its Sign in dialog. Signing in worked
 * every time; the worker then immediately manufactured another 401 and the box
 * reappeared. It locked a real user out of a live app for an afternoon.
 *
 * A worker cannot simply be deleted from the server: devices keep running the
 * copy they already have until a NEW script replaces it. So this stub exists
 * to be that replacement -- it unregisters itself and drops every cache it
 * finds. Once it has reached every device this file can go.
 *
 * If offline playback is wanted again, it must not intermediate authentication:
 * intercept ONLY /stems/*.mp3, never navigations, never /api/*, and it needs a
 * way to be tested against a real login before it ships.
 */
self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (e) => {
    e.waitUntil((async () => {
        for (const k of await caches.keys()) {
            if (k.startsWith('beatz-')) await caches.delete(k);
        }
        await self.registration.unregister();
        // Reload every open tab so nothing keeps running the old worker.
        for (const c of await self.clients.matchAll({ type: 'window' })) {
            try { c.navigate(c.url); } catch (err) {}
        }
    })());
});

// No fetch handler at all: every request goes straight to the network, and the
// browser handles authentication itself, the way it did before any of this.
