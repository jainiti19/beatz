# BeatznBox — product critique, competitive read and SWOT

**Date:** 26 August 2026
**Reviewed:** `beatznbox.wesimplyhome.com` (live, deployed build) plus the source in `~/git-repos/beatz`
**Reviewed by:** Claude, at Iti's request
**Altitude:** Track 1 (Experience Business). This is a strategy note, not a bug list.

---

## How this was tested, and what was not tested

Played two songs end to end, worked all four stem faders, all three presets, the queue,
the playlist controls and the request form, on **desktop only**. Then checked every
browser-side finding against the repo before writing it down.

Three things were **not** covered, and no conclusion below depends on them:

- **Audio quality was not assessed.** The review had no sound. Separation quality is the
  single most important property of this product and it is unmeasured here.
- **Mobile was not tested.** A window resize failed to take. There is a commit
  (`e61491e`, "Web player: stack into one column on a phone") suggesting a phone layout
  exists; it is unverified.
- **The live catalogue was not read directly** — the server needs credentials. Counts
  below come from the local working copy, which may be ahead of what is deployed.

**Four first-pass findings were checked and withdrawn.** They are recorded in
"Corrections" at the end rather than deleted, because three of them are the sort of
thing that would otherwise get repeated.

---

## What the product actually is

Not a karaoke app. A **stem player**: each song is split into Vocals / Drums / Bass /
Harmony with independent faders, wrapped in three presets:

| Preset | Vocals | Drums | Bass | Harmony |
|---|---|---|---|---|
| Karaoke | off | 80% | 80% | 80% |
| Unplugged | off | off | 80% | 80% |
| Jamming | off | 70% | 80% | 40% |

Around that sits a lyrics pane with word-level highlighting, an auto-advancing queue,
ad-hoc playlists, and a "request a song" form that routes to a human.

That distinction — stem player, not karaoke player — is the whole strategic story below.

---

## Critique

### What is genuinely strong

- **The stem mixer is the product.** Pulling drums for an acoustic sing, or ducking
  harmony so a live guitarist has room, is not something any karaoke product does.
  "Unplugged" and "Jamming" are not features; they are the reason to build this at all.
- **It plays the real master.** Singing over the actual recording minus the voice is a
  different experience from a cheap re-record, which is what most free alternatives are.
- **The lyric alignment engine is correct by construction.** `align-lyrics.py` uses
  torchaudio MMS_FA force alignment: it takes lyrics already known to be right and solves
  only for timing. Being non-autoregressive it cannot drift, hallucinate or reorder. This
  is the right architecture and it is already built and working.
- **The app grades its own lyric quality and says so.** `check-lyrics-quality.py` marks
  each song amber ("needs checking") or red ("unusable"), surfaced as a coloured dot with
  a tooltip. Shipping a visible admission that some data is bad is good engineering
  practice and rare.
- **Zero friction.** No install, no accounts, click a song and it plays.

### The real problems, worst first

**1. Two-thirds of the catalogue is still on the wrong lyrics pipeline.**

There are two generators in the repo and they produce very different quality:

- `align-lyrics.py` — force-aligns known-correct lyrics. Correct output.
- `generate-timed-lyrics.py` — Whisper `base`, *transcribing* sung Hindi. Its own
  docstring records that this produces garbage.

Counting the local `web/stems/` tree: **24 songs carry force-aligned real lyrics, 48 look
like Whisper output, and 2 have no timed lyrics at all** (`Aao_huzoor`,
`Tumhe_apna_banane_ki`). The 48 is a heuristic — songs whose real lyrics are legitimately
in Latin script (Pasoori, Senorita) may be false positives — so treat it as "roughly
two-thirds, spot-check before trusting the number".

What that looks like on screen: *Chalte Chalte* displays `vamos` / `de` /
"Never forget, never say anything." / "Bóc" — verified on disk, not a rendering artefact.
Per-word confidence scores of about **-5.3** sit in the file, which is why the grader
already flags it amber.

**So this is not a bug to diagnose. The correct pipeline exists and works. The job is
finishing the migration of the other 48.**

**2. Devanagari on screen will quietly kill the singalong.**

The force-aligned songs display correct lyrics — in देवनागरी. The audience for this (HK
Indian expats, second-generation kids, a mixed party crowd) largely cannot sight-read
Devanagari at tempo. They read romanised Hindi fine. Every commercial Hindi karaoke track
is romanised for exactly this reason.

**The romanisation already exists in the data.** MMS_FA romanises via uroman, so
`lyrics_timed.json` already stores word tokens like `mujhako`, `itanaa` alongside the
Devanagari line text. Rendering romanised words instead of, or under, the Devanagari line
is a display change against data already on disk — not a re-processing project.

A side effect of the same mismatch: on force-aligned songs the **word-level highlight does
not appear**, because the romanised word tokens do not match into the Devanagari line
string. Fixing the display fixes the highlight too.

**3. There is no "with vocals" mode.** All three presets have Vocals OFF. Someone who only
half-knows a song has nothing to lean on and stops singing after two lines. A fourth
preset at Vocals ~30% is close to a one-line change and is the highest value-per-hour item
on this list.

**4. The lyrics pane is a document, not a stage.** Small left-aligned dark-on-white text,
roughly twenty lines crammed into a side panel about a quarter of the screen width. A
party display needs dark ground, very large centred type, three to five lines visible, and
a full-screen / TV mode. Nobody sings off a laptop sidebar.

**5. Single screen, single queue, no phones.** No room code, no join, no shared queue.
"Up next" auto-fills with whatever is next alphabetically (Chalte Chalte → Channa Mereya)
and offers only *Skip*. Everyone has to crowd one laptop to choose a song. **This is the
largest gap against the "karaoke in a box" model** — the box is supposed to be the thing
everyone points their phone at.

**6. No key shift, no tempo control.** Every karaoke box has ±semitones. Bollywood
routinely puts men in Lata's range and women in Kishore's. This is the most-requested
control at real singalongs and it is absent.

**7. No mic path.** "Karaoke in a box" implies mic → speaker. Today it is bring-your-own
speaker and sing over it.

**8. The catalogue is closed and only grows through Iti.** ~74 songs; adding one means a
guest fills in a request form that routes to her, and she runs a pipeline. Fine for a
house party. Fatal for anything self-serve.

**9. Search is title-only.** Indian music gets chosen by *singer, film, decade, mood* —
"Kishore", "RD Burman", "90s", "sad", "dance". None of that exists.

**10. Playlist controls use native browser dialogs.** Both the "+" chip and the per-song
"+P" block the page until dismissed. On a phone that is an OS-level modal; on the party
laptop it freezes playback control. Should be inline UI. (Observed indirectly — the
blocking behaviour is what the automation hit — so treat as an observation, not a
confirmed defect.)

**11. Local `web/stems/songs.json` is a 226-byte malformed stub** — truncated mid-list and
not valid JSON. Almost certainly mid-regeneration by `add-songs.sh` (which is currently
modified in the working tree). Worth confirming before the next deploy, given the deploy
scripts do not mirror-delete.

---

## Versus YouTube, and the rest of the field

| | YouTube | Smule / StarMaker | BeatznBox |
|---|---|---|---|
| Catalogue | Effectively unlimited | Large, licensed, strong Bollywood | ~74, closed, request-only |
| The recording | Usually a cheap re-record or an artefacty vocal-strip | Licensed backing tracks | The real master, stem-separated |
| Lyrics | Burned in, usually **romanised**, always synced | Synced, romanised | Two-thirds unreliable; the good third is Devanagari |
| Stem control | None | None | The entire point |
| Live musicians | Impossible | Impossible | Unplugged / Jamming |
| Setup | Cast to any TV in ten seconds | Phone app | Laptop, sidebar, no TV mode |
| Between songs | Search, ads, thumbnails, dead air | Curated | Auto-queue |
| Social layer | Comments | Duets, scoring, following | None (deliberately) |
| Legality | Someone else's problem | Licensed | Ours |

**The honest read:** YouTube wins on everything a *guest* notices in the first thirty
seconds — catalogue, lyric legibility, TV-native playback. BeatznBox wins on the two
things a *host* and a *musician* notice — the recording is real, and instruments can be
removed from it. Right now the guest-facing half is the weaker half, which is the wrong
way round for a party product.

---

## SWOT

### Strengths
- Stem separation over original Indian masters — not available elsewhere for this
  catalogue at any price.
- Unplugged / Jamming: a live-band-in-a-box, not a karaoke box. No competitor category.
- A correct-by-construction lyric alignment engine, already built and working on 24 songs.
- Honest self-grading of lyric quality, surfaced in the UI.
- Curated Hindi/Bollywood catalogue with real taste in it — Mukesh and the RD-era through
  Coke Studio to current. The curation is itself an asset.
- Zero-friction web app on infrastructure already owned, at near-zero marginal cost.
- Feeds Track 1 directly: Bollywood Night 25 Sep, Good Ruckus events after.

### Weaknesses
- Lyrics — the most visible surface — are unreliable on roughly two-thirds of the
  catalogue, and unreadable-at-tempo on much of the rest.
- No romanised display, no key shift, no guide vocal, no mic, no TV mode, no phone queue.
- ~74 songs, growing only when Iti personally does work.
- Single-operator, single-screen model. Does not scale past one laptop and one host.
- Same key-person risk as the rest of the estate: only Iti can run, extend or fix it.

### Opportunities
- **Own a category nobody occupies: Indian live-singalong, not Indian karaoke.** Smule owns
  social karaoke, YouTube owns the long tail, nobody owns "real band, real recording, you
  are the singer".
- A phone-based queue turns an app into an *experience* — guests adding songs from their
  table is the differentiator against a DJ, and it is the natural Good Ruckus signature.
- Curated setlists per event type (Bollywood night, retro night, kids' party) are a
  productisable format.
- Licensed re-records, or a public-domain / independent Indian catalogue, would make a
  commercial version legally possible later.
- Diaspora demand beyond HK is real and underserved — but as an event format, not an app.

### Threats
- **Copyright is the existential one.** These are commercial masters, reproduced and turned
  into derivative stems. Rights holders in this catalogue — Saregama in particular, over
  exactly the vintage film music that makes up a large share of the list — litigate. A
  *ticketed* event adds a public-performance dimension on top. Flagged now because
  **Amazing Race on 5–6 December is the first paid event.**
- It runs on the same Hetzner box as Classbox and CashKitty production. A complaint or
  takedown points at infrastructure holding children's data and household financial data.
  The basic auth in place (see Corrections) substantially blunts this; it does not remove
  the shared-host concern.
- If YouTube or Smule ship decent Hindi stem separation, the technical moat goes overnight.
  The durable moat is curation and the event format, not the tech.
- Iti's own capacity. The standing shape is ≤1hr/day on apps with 4–5hrs elsewhere, and
  this competes directly with Nupur's billing week.

---

## Security / cyber / legal (operating rule 3)

- **Data security — clean.** No accounts, no login, no personal data beyond an optional
  name on the request form. Nothing to leak, nothing in backups that matters, no
  third-party API carrying user data.
- **Cybersecurity — adequate, and better than first assumed.** The site sits behind Caddy
  basic auth (`curl` without credentials returns 401 for both the page and
  `stems/songs.json`). Rotation is scripted in `scripts/set-web-password.sh`, which reads
  the password with echo off, hashes locally at cost 14, keeps plaintext out of argv,
  validates the Caddyfile and restores a backup on failure. That is the same discipline as
  `change-password.sh`. **No action needed.**
- **Legal — the open item.** Unlicensed reproduction and creation of derivative works
  under both the Indian Copyright Act 1957 and HK's Copyright Ordinance. Private use at a
  private party is a materially smaller risk than public distribution, and the basic auth
  keeps it on the private side of that line. Using it at a **ticketed** event is a
  different and larger question and should be answered before December.

**Recommendation:** keep the auth on, keep the catalogue off any public index, and treat
"can this be used at a paid event" as a decision to be taken deliberately rather than by
drift.

---

## What to actually do

### Before Bollywood Night, 25 September — four items
1. **Migrate the 25 Sep setlist to `align-lyrics.py`.** Not all 48. Pick the ~20 songs
   for that night and put them through the good pipeline.
2. **Render romanised lyrics** from the word tokens already in `lyrics_timed.json`. This
   also restores word-level highlighting on aligned songs.
3. **Full-screen dark lyric view**, large centred type.
4. **A "Sing along" preset** at Vocals ~30%.

### Next, if it earns it
5. **Key shift, ±3 semitones.**
6. **Phone queue with a room code.** This is what turns Beatz from Iti's app into Good
   Ruckus's instrument.

### Explicitly not now
More catalogue, scoring, accounts, or anything self-serve. And **stop treating this as a
product**. As a consumer app it is uninvestable on licensing alone. As the thing that makes
a Good Ruckus night different from a DJ, it is the strongest asset in Track 1.

---

## Corrections — first-pass findings that were checked and withdrawn

Recorded rather than deleted, per the standing rule that a plausible cause must be
confirmed before it is written down.

1. **"The site is fully public with no auth."** Wrong. `curl` returns **401** without
   credentials. The browser used for the review had cached basic-auth credentials for the
   host, so the login never appeared. This was the most consequential error in the first
   pass — it inflated the legal exposure considerably.
2. **"Kesariya's lyrics are not synced."** Wrong. They are force-aligned; line 1 legitimately
   spans 9.64–18.74s, so it was correctly highlighted at 0:15. What is genuinely missing is
   the *word-level* highlight, for the Devanagari/romanised mismatch described above.
3. **"The orange dot marks good songs, so the quality signal is inverted."** Backwards. The
   dot is a **warning** — amber "needs checking", red "unusable" — assigned by
   `check-lyrics-quality.py`. The system was correctly flagging its own bad data.
4. **"The catalogue is unstable: 74 songs with scraped YouTube titles on one load, 71 clean
   on the next."** Real, but already fixed earlier the same day by `cc8aff4` ("stop the
   song list being served from a stale cache"). The first load was the stale cache.

5. **Cause not confirmed:** the Whisper-versus-aligned split is read from file contents and
   the two scripts' documented behaviour. No pipeline was re-run to prove which generated
   which file. Confirm before relying on the count of 48.
