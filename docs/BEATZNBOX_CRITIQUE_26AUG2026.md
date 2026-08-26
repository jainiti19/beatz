# BeatznBox critique, 26 Aug 2026 — pointer

**This is not the document. It is a pointer to it.**

The critique lives in the MixedBag repo, which is its single source of truth:

    ~/Documents/Project_MixedBag/31_beatznbox_critique.md
    (jainiti19/MixedBag, private — indexed at 00_index.md entry 31)

**Edit it there. Do not copy it back here.** An earlier version of this file was a full
duplicate; that was wrong, and this replaces it. Two copies of a living document drift,
and the drift is silent.

Not a symlink on purpose: beatz sits outside `~/Documents/`, so an absolute link would
dangle on any other machine. Same reasoning as `HUB_CLAUDE.md`, which is deliberately not
symlinked into this repo.

---

## What it says that matters in this repo

Reviewed the live app plus this source tree. Full argument, the YouTube/Smule comparison
and the SWOT are in the MixedBag file; this is the engineering-relevant extract.

**Separation quality is good — confirmed by Iti, 26 Aug 2026.** The load-bearing property
of the product holds. Settled.

**The lyrics pipeline is half-migrated.** `align-lyrics.py` (torchaudio MMS_FA force
alignment over known-correct lyrics — non-autoregressive, so it cannot drift, hallucinate
or reorder) is the right architecture and works. `generate-timed-lyrics.py` (Whisper `base`
transcribing sung Hindi) does not, as its own docstring records.

- **24 of 74 songs are force-aligned. Around 48 still carry Whisper output. 2 have none**
  (`Aao_huzoor`, `Tumhe_apna_banane_ki`).
- The 48 is a heuristic over file contents, not proven by re-running anything — songs whose
  real lyrics are legitimately Latin-script (Pasoori, Senorita) may be false positives.
- Example on disk: `Chalte_Chalte/lyrics.txt` reads `vamos` / `de` / "Never forget, never
  say anything." with per-word scores near **-5.3**. `check-lyrics-quality.py` is correctly
  flagging it amber.

**Cheapest high-value fix.** MMS_FA romanises via uroman, so `lyrics_timed.json` already
holds romanised word tokens (`mujhako`, `itanaa`) beside the Devanagari line text.
Rendering those gives readable lyrics **and** restores word-level highlighting on aligned
songs — a display change, no re-processing. Devanagari at tempo is unreadable for most of
the intended audience, so this is not cosmetic.

**Other findings that stand:** no guide-vocal preset (all three presets are Vocals OFF, so
anyone who half-knows a song has nothing to lean on); no key/pitch shift; the lyric pane is
a small light-on-white side panel with no full-screen or TV mode; no phone queue or room
code (the auto-queue is alphabetical with only Skip); title-only search; playlist controls
use blocking native browser dialogs; and `web/stems/songs.json` in the working tree is a
226-byte malformed stub — worth checking before the next deploy, since the deploy scripts
do not mirror-delete.

**Four first-pass findings were checked and withdrawn** — recorded in the MixedBag file
rather than deleted. Most importantly: **this site IS behind Caddy basic auth** (`curl`
returns 401; the review browser had cached credentials), Kesariya *is* correctly aligned,
the coloured dot is a warning marker rather than a quality badge, and the stale song list
was already fixed by `cc8aff4` the same day.

**Suggested order before Bollywood Night, 25 Sep:** migrate only that night's ~20-song
setlist to `align-lyrics.py`; render romanised lyrics; full-screen dark lyric view; a
"Sing along" preset at Vocals ~30%. Then key shift, then the phone queue.
