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
  rushed   the same fault a size larger, and invisible to `crushed`. When the
           words carry a whole section the recording does not sing, alignment
           cannot drop it -- it packs the surplus into the nearest instrumental
           break and drags the neighbouring lines seconds ahead of the singer.
           Nakkadwale disco hid 17 unsung lines this way and graded `good` for
           two days: only three of its lines were under CRUSHED_SEC, because a
           line can be a comfortable 0.74s wide and still hold six words. Rate,
           not width, is the tell -- and it has to be read against the song's
           own median, since Kala Chashma sings faster throughout than
           Nakkadwale did at its worst. A contiguous RUN is what separates a
           mis-aligned block from a genuinely fast couplet.
  gap      one line covering 20s+ means the aligner lost the thread and spread
           a line across a passage it does not belong to.
  prelude  the opening line was force-fit onto the intro, so the highlight
           sweeps before anyone has sung and the room comes in early. Caught by
           the first line's Viterbi score against the song's *own* median --
           an absolute threshold cannot work, since a song aligned poorly
           throughout scores badly on every line.

Grades: good | check | bad.  Only bad and check are shown in the player, as an
amber and a red dot, so the two have to mean different things to someone
scanning the list for what to sing tonight.

  red    you cannot follow the words: none at all, or the highlight is wrong
         for a stretch long enough that the singer is lost rather than briefly
         annoyed. Racing counts sooner than parking -- a parked line still
         tells you where you are, while a racing block sweeps the words past
         and leaves you nowhere.
  amber  a rough patch you can sing through and would want fixed.

Each verdict also carries the KIND of fault, "words" or "timing", because the
two need opposite fixes and the player offers them. Pasting lyrics repairs
missing or invented words; it does nothing for a song whose words are right and
whose highlight parks for 42 seconds, and offering the paste box there sends
someone to retype a correct lyric.

Severity is read from the LONGEST RUN of consecutive rushed lines, not the
seconds it spans. Sagar Kinare has three rushed lines 28 seconds apart with an
instrumental between them, which is two small blemishes rather than half a
minute of chaos; Baahon Ke Darmiyan has twelve in a row.

Usage: check-lyrics-quality.py [web/stems]
"""
import json, os, re, statistics, sys

STEMS = sys.argv[1] if len(sys.argv) > 1 else "web/stems"

MIN_LINES      = 8
CRUSHED_SEC    = 0.35
CRUSHED_PCT    = 15
LONG_LINE_SEC  = 20
# 3x the song's own median, never below RUSHED_FLOOR, sustained over
# RUSHED_RUN lines. Measured over 125 songs: this flags 7, and takes
# Nakkadwale disco from a run of 7 before its unsung lines were cut to 1 after.
# The floor stops a slow ghazal, whose median is 0.8 w/s, reporting ordinary
# singing at 2.4 as a rushed block.
RUSHED_MULT    = 3.0
RUSHED_FLOOR   = 3.5     # words/second
RUSHED_RUN     = 4       # consecutive lines
LEAD_MARGIN    = 3.0     # score points below the song median; measured, see below
RUSHED_RED_RUN = 8       # consecutive racing lines that make a song unsingable
LONG_RED_SEC   = 30      # a highlight parked this long has stopped helping


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


def worst_fault(found):
    """Red beats amber; within a grade the first fault found is the headline."""
    found.sort(key=lambda f: -f[0])
    grade = "bad" if found[0][0] == 2 else "check"
    return grade, "; ".join(note for _, note in found[:2]), "timing"


def rushed_run(entries):
    """Longest run of consecutive lines sung impossibly fast for this song."""
    rates = []
    for e in entries:
        words = e.get("words") or []
        dur = e.get("end", 0) - e.get("start", 0)
        rates.append(len(words) / dur if words and dur > 0 else None)
    known = [r for r in rates if r]
    if len(known) < MIN_LINES:
        return 0
    limit = max(RUSHED_MULT * statistics.median(known), RUSHED_FLOOR)
    best = run = 0
    for r in rates:
        # A line with no word timings breaks the run rather than extending it:
        # the run is meant to be evidence of a packed block, and an unknown
        # line is not evidence.
        run = run + 1 if r and r > limit else 0
        best = max(best, run)
    return best


def grade(song_dir):
    tp = os.path.join(song_dir, "lyrics_timed.json")
    if not os.path.exists(tp):
        return "bad", "no timings", "words"
    try:
        entries = json.load(open(tp, encoding="utf-8"))
    except Exception:
        return "bad", "unreadable timings", "words"
    if not isinstance(entries, list) or len(entries) < MIN_LINES:
        return "bad", f"stub ({len(entries) if isinstance(entries, list) else 0} lines)", "words"

    text = " ".join(e.get("text", "") for e in entries)
    sc = script_of(text)
    # Bollywood lyrics reach us as roman or devanagari. Arabic script means
    # Whisper invented it — no real source in this library writes that way.
    if sc == "arabic":
        return "bad", "wrong script (whisper)", "words"

    durs = [e["end"] - e["start"] for e in entries if "end" in e and "start" in e]
    if not durs:
        return "bad", "no line timings", "words"
    crushed = sum(1 for d in durs if d < CRUSHED_SEC)
    pct = 100 * crushed / len(durs)
    longest = max(durs)

    # An opening line the model never found sat 4-6 points under its song's
    # median across the library, while a correctly placed one sits within about
    # 1. Gulabi Aankhein's read -6.72 against a median of -0.95 and pinned the
    # first line at 0.10s, 42s before the singer.
    scores = [e["score"] for e in entries if "score" in e]
    lead_off = None
    if len(scores) >= MIN_LINES:
        lead = scores[0] - statistics.median(scores)
        if lead < -LEAD_MARGIN:
            lead_off = f"opening line off ({lead:+.1f} vs median)"

    # Every fault, then the worst one decides the dot. Returning on the first
    # match hid the second: Mere Sapno Ki Rani reported a 42s line and never
    # mentioned that it also has a rushed block.
    found = []
    run = rushed_run(entries)
    if run >= RUSHED_RED_RUN:
        found.append((2, f"{run} lines race past the singer"))
    elif run >= RUSHED_RUN:
        found.append((1, f"{run} lines rushed"))
    if longest >= LONG_RED_SEC:
        found.append((2, f"highlight parked {longest:.0f}s on one line"))
    elif longest > LONG_LINE_SEC:
        found.append((1, f"{longest:.0f}s line"))
    if pct > CRUSHED_PCT:
        found.append((1, f"{pct:.0f}% crushed lines"))
    if lead_off is not None:
        found.append((1, lead_off))
    if found:
        return worst_fault(found)
    return "good", "devanagari" if sc == "devanagari" else "", ""


def main():
    manifest = os.path.join(STEMS, "songs.json")
    songs = json.load(open(manifest, encoding="utf-8"))
    tally = {"good": 0, "check": 0, "bad": 0}
    for s in songs:
        g, why, fault = grade(os.path.join(STEMS, s["dir"]))
        s["lyrics"] = g
        if why:
            s["lyricsNote"] = why
        elif "lyricsNote" in s:
            del s["lyricsNote"]
        if fault:
            s["lyricsFault"] = fault
        elif "lyricsFault" in s:
            del s["lyricsFault"]
        tally[g] += 1
    json.dump(songs, open(manifest, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"  lyrics graded: {tally['good']} good, {tally['check']} check, {tally['bad']} bad")
    for s in songs:
        if s["lyrics"] != "good":
            print(f"    {s['lyrics']:6} {s['name'][:44]:46} {s.get('lyricsNote','')}")


if __name__ == "__main__":
    main()
