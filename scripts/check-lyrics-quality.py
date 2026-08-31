#!/usr/bin/env python3
"""Grade each song's lyrics and write the verdict into songs.json.

Every failure mode here is one we have actually shipped to the player and only
noticed by playing the song:

  missing  no timings at all, or so few that the file is a stub. Pal Pal Dil Ke
           Paas had four "lines" — you / centered / FOR WALKING ABOUT — which
           looks like success to any check that only asks whether the file
           exists.
  garbage  Whisper transcribed sung Hindi into another script entirely. Tu Hai
           To Dil Dhadakta Hai came out as Urdu. Detected by script, not by
           confidence score, because Whisper is happily confident about it.
  crushed  the aligner must place every line in order, so a line the singer
           never sang collapses to near-zero width and flashes past.
  gap      one line covering 20s+ means the aligner lost the thread and spread
           a line across a passage it does not belong to.
  prelude  the opening line was force-fit onto the intro, so the highlight
           sweeps before anyone has sung and the room comes in early. Caught by
           the first line's Viterbi score against the song's *own* median --
           an absolute threshold cannot work, since a song aligned poorly
           throughout scores badly on every line.

Grades: good | check | bad.  Only bad and check are shown in the player.

Usage: check-lyrics-quality.py [web/stems]
"""
import json, os, re, statistics, sys

STEMS = sys.argv[1] if len(sys.argv) > 1 else "web/stems"

MIN_LINES      = 8
CRUSHED_SEC    = 0.35
CRUSHED_PCT    = 15
LONG_LINE_SEC  = 20
LEAD_MARGIN    = 3.0     # score points below the song median; measured, see below


def script_of(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "none"
    counts = {"latin": 0, "devanagari": 0, "arabic": 0, "other": 0}
    for c in letters:
        o = ord(c)
        if o < 0x250:                    counts["latin"] += 1
        elif 0x900 <= o <= 0x97F:        counts["devanagari"] += 1
        elif 0x600 <= o <= 0x6FF or 0x750 <= o <= 0x77F: counts["arabic"] += 1
        else:                            counts["other"] += 1
    return max(counts, key=counts.get)


def grade(song_dir):
    tp = os.path.join(song_dir, "lyrics_timed.json")
    if not os.path.exists(tp):
        return "bad", "no timings"
    try:
        entries = json.load(open(tp, encoding="utf-8"))
    except Exception:
        return "bad", "unreadable timings"
    if not isinstance(entries, list) or len(entries) < MIN_LINES:
        return "bad", f"stub ({len(entries) if isinstance(entries, list) else 0} lines)"

    text = " ".join(e.get("text", "") for e in entries)
    sc = script_of(text)
    # Bollywood lyrics reach us as roman or devanagari. Arabic script means
    # Whisper invented it — no real source in this library writes that way.
    if sc == "arabic":
        return "bad", "wrong script (whisper)"

    durs = [e["end"] - e["start"] for e in entries if "end" in e and "start" in e]
    if not durs:
        return "bad", "no line timings"
    crushed = sum(1 for d in durs if d < CRUSHED_SEC)
    pct = 100 * crushed / len(durs)
    longest = max(durs)

    # An opening line the model never found sat 4-6 points under its song's
    # median across the library, while a correctly placed one sits within about
    # 1. Gulabi Aankhein's read -6.72 against a median of -0.95 and pinned the
    # first line at 0.10s, 42s before the singer.
    scores = [e["score"] for e in entries if "score" in e]
    if len(scores) >= MIN_LINES:
        lead = scores[0] - statistics.median(scores)
        if lead < -LEAD_MARGIN:
            return "check", f"opening line off ({lead:+.1f} vs median)"

    if pct > CRUSHED_PCT:
        return "check", f"{pct:.0f}% crushed lines"
    if longest > LONG_LINE_SEC:
        return "check", f"{longest:.0f}s line"
    return "good", "devanagari" if sc == "devanagari" else ""


def main():
    manifest = os.path.join(STEMS, "songs.json")
    songs = json.load(open(manifest, encoding="utf-8"))
    tally = {"good": 0, "check": 0, "bad": 0}
    for s in songs:
        g, why = grade(os.path.join(STEMS, s["dir"]))
        s["lyrics"] = g
        if why:
            s["lyricsNote"] = why
        elif "lyricsNote" in s:
            del s["lyricsNote"]
        tally[g] += 1
    json.dump(songs, open(manifest, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"  lyrics graded: {tally['good']} good, {tally['check']} check, {tally['bad']} bad")
    for s in songs:
        if s["lyrics"] != "good":
            print(f"    {s['lyrics']:6} {s['name'][:44]:46} {s.get('lyricsNote','')}")


if __name__ == "__main__":
    main()
