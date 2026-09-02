# Making a song load fast on the phone

Written 2 Sep 2026, after two failed attempts at the hosting half of this.
Read the rollout section before touching anything live.

## The two different slow loads

They have different causes and different fixes, and conflating them is why the
last attempt tried to solve everything with one switch.

| symptom | cause | fix |
|---|---|---|
| a song **nobody on this device** has played takes 13-20s | 22MB pulled from Nuremberg; 305ms RTT, 83-89% of the time is transfer | serve the audio from Cloudflare's edge (**Part B**) |
| a song played **last week** is slow again | nothing persists it; Chrome's HTTP cache is evictable and evicts | hold it in the Cache API (**Part A**) |

Iti reported the second one on 2 Sep: *"phone is slow for songs I haven't
played recently"*. That is Part A, and Part A needs no hosting change at all.

## Part A — hold the audio on the device, with no service worker

**The Cache API does not require a service worker.** `caches.open()` and
`cache.put()` work from the page, and a page's own `fetch()` carries the site's
basic-auth credentials automatically because the browser attaches them to
same-origin requests it initiates. So the page can fill the cache, and the page
can read from it before going to the network.

That matters because a service worker is the one thing here that provably
cannot work: its fetches are *not* the page's, they carry no credentials, they
401, and a browser answers a 401 by re-opening its Sign in dialog. That is what
locked a real user out of the live site on 2 Sep.

So Part A is: **no service worker, ever, on the authenticated origin.** The
download UI, the progress row, the Saved filter and `refreshOfflineDirs()` all
still exist in `index.html` and were tested when they shipped; only two things
were missing.

1. `fetchStem()` and the lyrics loads must look in the cache before the network.
2. A song that is played should be *put* in the cache, so the common case —
   "I played this last week" — is fixed without anyone pressing a button.

Passive caching writes a clone of the response, which briefly holds the stem
twice. That is 6MB a stem, not the 22MB-alongside-390MB case the prefetch
comments warn about, and it is skipped when the fetch came from the cache in
the first place.

`web/sw.js` stays the self-unregistering stub. Do not revive it.

## Part B — serve the audio from the edge

The bucket (`beatznbox-stems`, APAC, private, 2.4GB) and the Worker
(`server/r2-worker`) already exist. What changes is **how the Worker
authenticates**, and that single change is what makes the rest safe.

### The problem with basic auth, stated properly

The Worker checked the same basic-auth password as Caddy. Three consequences,
and every one of them caused an outage or a dead end:

1. It had to run on **the player's own hostname**, because a browser only sends
   an Authorization header to the origin that asked for it. So enabling it meant
   putting a Worker route in front of the live site — and when it was wrong, the
   live site was wrong.
2. Browsers key credentials by `(origin, realm)`. Caddy's realm is `restricted`;
   announcing anything else means the browser never offers the password it
   holds, and every stem 401s. That is failure #1 of 2 Sep.
3. **I cannot test it.** I do not have the password. I could verify that a wrong
   password is rejected and never that a right one is accepted, so the only
   place the success path could be exercised was production, on Iti's device.
   That is the actual root cause of both outages.

### The change: a signed token, not a password

The Worker verifies an HMAC token supplied in the query string.

    token   = v1.<exp>.<base64url(HMAC-SHA256(key, "v1." + exp))>
    request = https://<stems-host>/stems/Kesariya/vocals.mp3?t=<token>

- **Minted by** `GET /api/stem-token` on the queue service, which sits behind
  Caddy's basic auth — so only someone who already logged in can get one.
- **Verified by** the Worker with WebCrypto and a constant-time compare.
- **Lifetime 7 days**, refreshed on every page load. A leaked URL stops working;
  the password itself is never exposed to the Worker or to me.
- **Not bound to a path.** One token unlocks the library, which is exactly the
  authority the logged-in user already has. Binding per file would mean 440
  tokens and would put a varying string in every cache key.

Four things follow, and they are the whole point:

- **The same-origin requirement disappears.** The stems can be served from a
  hostname that is not the player's, so *the live site has no Worker route in
  front of it* and cannot break the way it did twice.
- **The realm problem disappears** — there is no realm.
- **It is testable by me.** I can mint a token from the shared key and curl the
  Worker end to end. The success path stops being something only production can
  exercise.
- The Cache API keys on the URL, so **the token must be stripped from the cache
  key**; otherwise a token refresh orphans every held song. Cache under the
  bare URL, send the token only on the wire.

### Who holds the key

I generate the shared key and set it in both places. It grants exactly one
capability — reading stems — and I already hold the entire library on this
laptop, so it gives me nothing I do not have. It is not the site password and
cannot be turned into it. Rotate it by writing a new key in both places; every
outstanding token dies at once.

## Rollout — the part that was missing

The default path on the live site does not change until Iti has personally
loaded a song over the new one. Enforced by a query flag, not by discipline.

1. `wrangler dev --remote` against the real bucket. I check: valid token 200s,
   expired 401s, tampered 401s, missing 401s, Range gives 206, unknown key 404s.
   **No production impact.**
2. Deploy with `workers_dev = true`. This is safe now and was not before: the
   Worker is HMAC-protected, so a public URL is not an open door. I verify from
   the laptop with curl against real R2.
3. Iti opens the player with **`?stems=edge`** on the phone. That session alone
   uses the Worker; every other visitor is untouched. They report the timing.
4. Only then does the default constant flip, with **`?stems=origin`** left in as
   the way back.

Rollback at every stage is a query parameter or a one-line constant. At no
point is there a Worker route on `beatznbox.wesimplyhome.com`.

### What Iti has to do

- Nothing for Part A.
- For Part B: run one `scp`/restart for the queue service and one `wrangler
  secret put`, or approve me doing them. Then step 3 — load a song with
  `?stems=edge` and say whether it is faster.

## What this does not fix

Part B only helps the *first* play of a song on a device. Part A is what makes
the second and every later play fast. If Part B turns out to be a small gain on
top of Part A, stopping after Part A is a reasonable place to stop.
