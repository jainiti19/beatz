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
  silence  the line sits where nobody is singing. Every check above reads only
           the timings file, so none of them can tell a line placed on the
           singer from the same line placed on a dhol break: Mehbooba and Love
           Dose both graded `good` with their first thirty seconds of words laid
           over an intro, and Raah Mein Unse Mulaqat ran 30s ahead of the song
           for two days. This one opens the vocal stem and asks. Three shapes,
           because they are three different noises in the room:
             lead-in  the words start seconds before the first note is sung.
             block    a run of consecutive lines over one silent stretch --
                      Chaiyya Chaiyya parks nine lines in the dhol break at
                      4:30. Consecutive matters: the scattered single lines are
                      echo repeats ("sayonee (sayonee)") a second wide and
                      nobody notices them.
             parked   one line held over a whole instrumental interlude.

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
import base64, json, os, re, statistics, subprocess, sys, wave

STEMS = sys.argv[1] if len(sys.argv) > 1 else "web/stems"

# web/stems holds mp3s; the wavs the aligner actually read live in the demucs
# output. Reading the wav is ~0.3s a song against ~2.5s to decode the mp3, so
# the wav is worth finding — but the mp3 is a real fallback, because a copy of
# web/stems on its own has to grade the same way this laptop does.
STEMS_SRC = os.environ.get("BEATZ_STEMS_SRC",
                           os.path.expanduser("~/Music/karaoke/htdemucs"))

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

# --- silence checks -------------------------------------------------------
# The mask is align-lyrics.py's voiced_mask() rule, kept deliberately identical:
# RMS per 20ms frame, voiced when it is within 35dB of the song's loudest frame.
# The aligner decides what counts as singing that way, so a grader using a
# different rule would argue with it rather than check it.
FRAME_SEC      = 0.02
VOICED_DB      = 35      # below the song's peak frame
SILENT_VF      = 0.25    # a line under this voiced fraction is "on silence"
# A block is consecutive silent lines. Three at 1.3s each is Gali Mein Aaj
# Chand Nikla's echo tail, which nobody has ever complained about, so the block
# has to be worth some seconds too: measured over the library, the blocks of
# 6s+ are all real (Sham 15s, Sagar Kinare 13s, Chaiyya Chaiyya 27s, Mehbooba
# 23s, Love Is An Open Door 8s) and every block under it is echo repeats.
SILENT_RUN     = 3
SILENT_BLOCK_SEC = 6.0
SILENT_RED_SEC = 30.0    # Chaiyya's 27s dhol break is the worst still singable
# One line held over an interlude. Measured as the line's *silent* seconds, not
# its length: Saiyaan's quiet tail line is 9.6s long but a tenth of it is sung,
# and banke tera jogi's staccato alaap line is 11s long with 9.3s of silence in
# it. Both are fine. Afreen Afreen's is 11.7s of nothing at all.
PARKED_SIL_SEC = 10.0
# Lead-in: the first line's start against the first solid voiced onset. Nine
# songs in the library start their words before their singing; the honest ones
# are Mere Sapno Ki Rani at 7.0s and banke tera jogi at 10.0s, and the faults
# begin at Sayoonee's 12.5s. Red is reserved for the pair that put half a minute
# of words over the intro (Mehbooba and Love Dose, both +30.5), because there
# the room comes in a whole section early rather than a breath early.
LEAD_SEC       = 11.0
LEAD_RED_SEC   = 25.0
# What counts as the onset. A held note gives 0.2s of continuous voicing easily;
# an alaap does not -- banke tera jogi's opening "haa haa haa" is a run of
# 0.1s hits, and reading it strictly put its onset 12s late and turned a good
# song into a fault. Closing gaps up to half a second first fixes that song and
# moves no other song in the library by a frame.
ONSET_RUN_SEC  = 0.2
ONSET_GAP_SEC  = 0.5


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


def vocals_path(song_dir):
    """The vocal stem to listen to: the aligner's wav if it is still on disk."""
    name = os.path.basename(os.path.normpath(song_dir))
    for p in (os.path.join(song_dir, "vocals.wav"),
              os.path.join(STEMS_SRC, name, "vocals.wav"),
              os.path.join(song_dir, "vocals.mp3")):
        if os.path.exists(p):
            return p
    return None


def read_mono(path):
    """Mono float samples and their rate, or None if nothing can read them."""
    import numpy as np
    if path.endswith(".wav"):
        with wave.open(path) as w:
            if w.getsampwidth() == 2:
                ch, rate = w.getnchannels(), w.getframerate()
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
                pcm = pcm.astype(np.float32) / 32768.0
                return (pcm.reshape(-1, ch).mean(axis=1) if ch > 1 else pcm), rate
    # 32-bit float wavs and mp3s both land here.
    out = subprocess.run(["ffmpeg", "-v", "quiet", "-i", path,
                          "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if out.returncode != 0 or not out.stdout:
        return None
    return np.frombuffer(out.stdout, dtype="<i2").astype(np.float32) / 32768.0, 16000


_cache, _cache_dirty = None, False


def voiced_frames(song_dir):
    """Per-20ms 'someone is singing here' mask for this song, or None.

    Decoding the stems is the whole cost of this script -- a minute for the
    library against a second for everything else -- and the watcher reruns the
    grade after every single new song. So the mask is cached against the audio
    file's mtime and size: unchanged songs are never opened twice.
    """
    global _cache, _cache_dirty
    import numpy as np
    if _cache is None:
        try:
            _cache = json.load(open(os.path.join(STEMS, ".voiced-cache.json")))
        except Exception:
            _cache = {}
    path = vocals_path(song_dir)
    if not path:
        return None
    st = os.stat(path)
    key, name = f"{st.st_mtime_ns}:{st.st_size}", os.path.basename(os.path.normpath(song_dir))
    hit = _cache.get(name)
    if hit and hit.get("key") == key:
        bits = np.frombuffer(base64.b64decode(hit["bits"]), dtype=np.uint8)
        return np.unpackbits(bits)[:hit["n"]].astype(bool)

    pcm = read_mono(path)
    if pcm is None:
        return None
    samples, rate = pcm
    hop = int(FRAME_SEC * rate)
    n = len(samples) // hop
    if n < 1:
        return None
    rms = np.sqrt((samples[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    db = 20 * np.log10(rms + 1e-10)
    voiced = db > db.max() - VOICED_DB
    _cache[name] = {"key": key, "n": int(n),
                    "bits": base64.b64encode(np.packbits(voiced)).decode()}
    _cache_dirty = True
    return voiced


def save_voiced_cache():
    if _cache_dirty:
        try:
            json.dump(_cache, open(os.path.join(STEMS, ".voiced-cache.json"), "w"))
        except Exception:
            pass                       # a cache that cannot be written is not a failure


def first_onset(voiced):
    """Seconds to the first stretch of real singing, or None if there is none."""
    import numpy as np
    filled = voiced.copy()
    gap = int(ONSET_GAP_SEC / FRAME_SEC)
    edge = np.diff(np.concatenate(([0], (~voiced).view(np.int8), [0])))
    for a, b in zip(np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)):
        if a > 0 and b < len(voiced) and b - a <= gap:
            filled[a:b] = True         # one alaap, not a dozen separate hits
    need = int(ONSET_RUN_SEC / FRAME_SEC)
    edge = np.diff(np.concatenate(([0], filled.view(np.int8), [0])))
    for a, b in zip(np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)):
        if b - a >= need:
            return a * FRAME_SEC
    return None


unheard = []


def silence_faults(song_dir, entries):
    """Faults that need the audio: lines placed where nobody is singing."""
    try:
        voiced = voiced_frames(song_dir)
    except Exception:
        voiced = None                  # numpy missing, unreadable stem: say nothing
    if voiced is None or not voiced.any():
        # Counted, not swallowed. A missing (or wholly silent) stem means this
        # song was graded with the old blind checks only, and that is worth
        # knowing before someone trusts a green dot.
        unheard.append(os.path.basename(os.path.normpath(song_dir)))
        return None
    import numpy as np
    cum = np.concatenate([[0], np.cumsum(voiced)])

    found = []
    run = run_sec = 0
    block = (0, 0.0)                   # the worst block, reported once
    parked = 0.0
    for e in entries:
        start, end = e.get("start"), e.get("end")
        if start is None or end is None or end <= start:
            run = run_sec = 0
            continue
        i = max(0, min(int(start / FRAME_SEC), len(voiced)))
        j = max(i, min(int(end / FRAME_SEC), len(voiced)))
        frac = float(cum[j] - cum[i]) / (j - i) if j > i else 0.0
        if frac >= SILENT_VF:
            run = run_sec = 0
            continue
        run, run_sec = run + 1, run_sec + (end - start)
        parked = max(parked, (end - start) * (1 - frac))
        if run_sec > block[1]:
            block = (run, run_sec)
    if parked >= PARKED_SIL_SEC:
        found.append((1, f"line parked on {parked:.0f}s of silence"))
    if block[0] >= SILENT_RUN and block[1] >= SILENT_BLOCK_SEC:
        found.append((2 if block[1] >= SILENT_RED_SEC else 1,
                      f"{block[0]} lines over {block[1]:.0f}s of silence"))

    onset = first_onset(voiced)
    first = entries[0].get("start")
    if onset is not None and first is not None:
        lead = onset - first
        if lead > LEAD_SEC:
            found.append((2 if lead >= LEAD_RED_SEC else 1,
                          f"words start {lead:.0f}s before the singing"))
    return found


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
    found += silence_faults(song_dir, entries) or []
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
    save_voiced_cache()
    json.dump(songs, open(manifest, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"  lyrics graded: {tally['good']} good, {tally['check']} check, {tally['bad']} bad")
    if unheard:
        print(f"    (no vocal stem for {len(unheard)}: {', '.join(unheard[:3])}"
              f"{'...' if len(unheard) > 3 else ''} — silence checks skipped)")
    for s in songs:
        if s["lyrics"] != "good":
            print(f"    {s['lyrics']:6} {s['name'][:44]:46} {s.get('lyricsNote','')}")


if __name__ == "__main__":
    main()
