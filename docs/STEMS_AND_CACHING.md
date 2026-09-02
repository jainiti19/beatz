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

---

## What was actually built, 2 Sep

Part A is **live**. Part B is built and **switched off**, waiting on one command
and one unknown.

### Decisions taken during the build, that the design above did not anticipate

- **Only the mp3s go to the edge.** songs.json and the lyrics stay on the
  origin: the manifest must be fresh on every load, and lyrics_timed.json is
  rewritten in place by a realign, so putting either in a bucket would add a
  sync obligation for a few KB of gain.
- **The edge hostname comes from the server, not the page.** The token endpoint
  returns `base` alongside the token, read from `/opt/beatznbox/stem-edge.url`.
  A workers.dev hostname carries an account subdomain nobody should have to
  remember, and a page compiled against a stale one would fail in a way that
  looks exactly like an outage. **Absent or empty file = no edge**, and the
  player silently uses the origin. That is why everything shipped today is
  inert.
- **Cache keys are always the origin URL**, whichever host served the bytes.
  Proven in the browser: a song downloaded through a stand-in edge then played
  with the edge off needed **zero** network calls. Flipping `?stems=` costs
  nobody a re-download, and neither will the eventual default flip.
- **The Worker has a `/_keys` listing**, token-protected. The bucket was filled
  by hand and nothing in the repo recorded the key layout, so checking whether
  a file is there meant guessing paths one at a time. It returns names and
  sizes, never bytes.

### The one unknown: the R2 key layout

`bucket info` reports 651 objects and 2.52GB — the library is there — but every
key guessed for it came back "does not exist": `Kesariya/vocals.mp3`,
`stems/Kesariya/vocals.mp3`, `web/stems/...`, `songs.json`. So the Worker's
`/stems/<dir>/<file>` -> `<dir>/<file>` mapping **may be wrong**, and if it is,
every stem 404s (not 401s — the distinction tells you which half is broken).

`GET /_keys?t=<token>&limit=20` answers this in one call the moment the Worker
is deployed. Fix the prefix in `index.js` if it differs, and redeploy.

### Verified before deploying, not after

- 17 Worker tests under Node with R2 stubbed
  (`node server/r2-worker/test/auth.test.mjs`): valid token accepted; missing,
  empty, malformed, wrong-key, tampered-expiry and expired tokens all refused;
  an unconfigured Worker serves nobody; a 401 never carries
  `WWW-Authenticate`, so it can never make a browser open a Sign in dialog;
  Range answers 206; CORS granted to the player origin and withheld from
  others.
- **Cross-language**: a token minted by the queue service's own
  `mint_stem_token()` on the VPS is accepted by the Worker's JavaScript
  verifier. The Python-signs / JavaScript-verifies seam is the one a unit test
  on either side alone would have missed.
- In the browser against a stand-in Worker: requests go to the edge carrying
  the token, responses are read through CORS, cache keys stay token-free, and
  when the stand-in omitted its CORS headers the player said **"Failed to
  load"** in the status line rather than hanging.

### Still to do, in order

1. **Deploy the Worker.** `cd server/r2-worker && npx wrangler@4.86.0 deploy`.
   Pin 4.86.0: newer wrangler needs Node 22 and this laptop is on 20, whose
   version the watcher service's PATH is pinned to. The deploy prints the
   workers.dev hostname.
2. **Check the key layout** with `/_keys` (above) before anything else.
3. **Point the site at it**: write that hostname into
   `/opt/beatznbox/stem-edge.url` on the VPS. Nothing changes for anyone —
   the player only reads `base` when asked with `?stems=edge`.
4. **Measure on the phone** with `?stems=edge`, against 13-20s cold today.
5. Only then flip the default, keeping `?stems=origin` as the way back.
