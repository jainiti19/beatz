#!/usr/bin/env python3
"""Fetch lyrics from LRCLIB.

Genius returns nothing usable for classic Hindi film songs — wrong song, or a
transliteration nobody sings from. LRCLIB is community-synced karaoke data, so
it covers Bollywood well and often carries per-line timings already.

We take only the words. Timing comes from align-lyrics.py, which solves against
this song's actual audio; LRCLIB's own timings are for whichever upload the
contributor had, which is rarely the same cut.

Search strategy matters more than it looks. Measured over 29 real requests,
**15 returned zero hits** — and the dominant cause was our own query: we sent
"title artist" as one string, and LRCLIB matches that near-literally, so the
artist usually drove a good title to nothing ("Aao huzoor" 20 hits, "Aao huzoor
Asha bhonsle" 0). So: search the TITLE alone, and use the artist only to RANK
what comes back.

The second cause is spelling — requests are typed from memory, and LRCLIB wants
the title near-exact ("tum itna kyun muskura rahe" 0 hits; the real "Tum Itna
Jo Muskura Rahe Ho" 20). Shortening the typed title does not fix it: prefixes
DO find hits, but they are other songs ("Hum pyaar karne wale" -> "I'm coming
in to get my shits").

What fixes it is asking something that already knows how to spell. YouTube's
search is fuzzy where LRCLIB's is literal, and we run it anyway to get the
audio — so the video we downloaded carries a correctly spelled title, and we
were throwing it away. "Tu kisi raii si" downloads a video called "Tu Kisi Rail
Si - Masaan | ...", and "Damadam mast kalandar" one called "Dama Dam Mast
Qalandar" — neither typed string finds anything on LRCLIB; both real titles do.
So --yt-title takes that raw video title, strips the decoration YouTube uploads
carry, and tries the results as queries in confidence order, the typed string
last.

Candidates are tried, not trusted: each one still has to clear score(), which
gates on title overlap, duration and cover markers. Wrong lyrics that look
right are worse than none — see the Zingaat case in the project notes — so a
candidate must earn its place, and no-result is still an honest answer.

Usage:
    fetch-lyrics-lrclib.py "song name" out.txt              # search and write
    fetch-lyrics-lrclib.py "song name" out.txt --artist X   # X ranks, never filters
    fetch-lyrics-lrclib.py "song name" out.txt --duration 275
    fetch-lyrics-lrclib.py "typed name" out.txt --yt-title "<raw youtube title>"
    fetch-lyrics-lrclib.py --show "song name"               # list candidates only
"""
import json, os, re, sys, urllib.parse, urllib.request

API = "https://lrclib.net/api/search"
UA = {"User-Agent": "beatznbox/1.0 (personal singalong library)"}


def _get(params, limit=20):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)[:limit]
    except Exception:
        return []


def search(query, limit=20):
    """Free-text search — what --show uses, and the first thing main() tries."""
    return _get({"q": query}, limit)


def gather(title, artist=None, limit=20):
    """Every candidate worth considering, de-duplicated.

    Two channels, because they fail differently: `q=` is fuzzy and forgiving,
    `track_name=` is structured and finds things `q=` misses (it was the only
    thing that found Aao Huzoor). The artist is deliberately NOT sent to the
    API — it is a ranking signal in pick(), not a filter."""
    out, seen = [], set()
    for hits in (_get({"q": title}, limit), _get({"track_name": title}, limit)):
        for h in hits:
            key = (h.get("trackName"), h.get("artistName"), h.get("duration"))
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
    return out


def describe(h):
    dur = h.get("duration") or 0
    lyr = h.get("plainLyrics") or ""
    n = len([l for l in lyr.split("\n") if l.strip()])
    return (f"{h.get('trackName','?')[:34]:36} {h.get('artistName','?')[:22]:24} "
            f"{int(dur//60)}:{int(dur%60):02d}  {n:3d} lines  {script_of(lyr):8}"
            f"{'  [synced]' if h.get('syncedLyrics') else ''}")


def script_of(text):
    """Roman and Devanagari are the two the room reads, and we have no
    preference between them. Everything else — Shahmukhi on the Coke Studio
    uploads, Gurmukhi on the Punjabi ones — is a last resort, taken only when
    a song offers nothing better."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "none"
    singable = sum(1 for c in letters
                   if ord(c) < 0x250 or 0x900 <= ord(c) <= 0x97F)
    return "singable" if singable * 2 > len(letters) else "other"


COVER_MARKERS = ("version", "cover", "remix", " mix", "lofi", "slowed",
                 "reverb", "mashup", "instrumental")

# Decoration that YouTube uploads carry and LRCLIB has never heard of. Stripped
# only from the ENDS of a candidate, never from the middle: "Guncha Koi Song"
# should lose its "Song", but a title that genuinely contains one of these words
# must keep it.
TITLE_JUNK = {
    "official", "video", "audio", "song", "full", "hd", "4k", "lyrics",
    "lyrical", "lyricvideo", "remastered", "quality", "original", "movie",
    "presents", "exclusive", "new", "latest", "with", "by", "ft", "feat",
    "popular", "most", "qawwali", "soundtrack", "ost", "track", "hq",
}
_BRACKETED = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_QUOTED = re.compile(r'"([^"]{4,})"|\u201c([^\u201d]{4,})\u201d')
# Not a plain hyphen: "Film-song" glues the two together with no spaces and is
# handled separately, while " - " really is a separator.
_SPLITS = re.compile(r"\s*[|•·]\s*|\s+[-–—]\s+")


def _tidy(s):
    """One candidate, stripped of brackets, junk and stray punctuation."""
    s = _BRACKETED.sub(" ", s or "")
    s = re.sub(r"\s+", " ", s).strip(" \t\"'`.,:;!-–—_")
    words = s.split()
    while words and words[0].lower().strip(".,:;") in TITLE_JUNK:
        words.pop(0)
    while words and words[-1].lower().strip(".,:;") in TITLE_JUNK:
        words.pop()
    return " ".join(words).strip(" .,:;-–—")


def title_candidates(typed, yt_title=None):
    """Queries to try, most trustworthy first, de-duplicated.

    The typed string goes last rather than first: it is the one input we know
    is unreliable, since it was typed from memory by whoever asked."""
    out = []

    def add(c):
        c = _tidy(c)
        if c and len(c) > 2 and c.lower() not in {x.lower() for x in out}:
            out.append(c)

    if yt_title:
        # A quoted span is the uploader naming the song explicitly, which beats
        # anything we could infer: '"Dama Dam Mast Qalandar" most popular
        # Qawwali, By: Runa Laila'.
        q = _QUOTED.search(yt_title)
        if q:
            add(q.group(1) or q.group(2))
        parts = [p for p in _SPLITS.split(yt_title) if p and p.strip()]
        # Which side of a separator holds the song depends on the upload's
        # convention: "Song | Film | Singer" puts it first, but the Western
        # "Artist - Song" puts it last. Taking the head unconditionally asked
        # LRCLIB for "Bruno Mars" and got back Bruno Mars' "Natalie" -- right
        # artist, wrong song, and it passed every gate because a candidate is
        # judged against itself. What was actually asked for settles it, so
        # order the parts by how much of the request each one contains. The
        # sort is stable, so a useless typed string leaves the order alone.
        if len(parts) > 1:
            parts.sort(key=lambda part: -_word_overlap(typed, part))
        for part in parts:
            # "Delhi Belly-nakkadwale disco udhaarwaley khisko" — film glued to
            # the front with no spaces, which _SPLITS deliberately does not
            # break on. The song is the far side, so try that before the whole.
            if "-" in part:
                tail = part.rsplit("-", 1)[-1]
                if len(tail.split()) >= 2:
                    add(tail)
            add(part)
        add(yt_title)
    add(typed)
    return out


def is_cover(h):
    """LRCLIB files foreign-language covers under the original's name, so a
    Gerua search answers with "Warna Cinta (Gerua - Malay Version)" — Indonesian
    words, and longer than the original, so most-lines-wins picks it over the
    real thing. Anything announcing itself as a version of the song is not the
    recording we just separated."""
    name = " ".join((h.get("trackName") or "").split()).lower()
    return any(m in name for m in COVER_MARKERS)


def _words(text):
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split() if w]


# "[00:19.90] Make the stars look like they're not shining" -- some LRCLIB
# contributors paste synced LRC straight into the plainLyrics field, and Bruno
# Mars' entry is one of them: 56 of its 57 lines carried a timestamp. Written
# through verbatim those render on screen, and the aligner would try to sing
# them. Also drops the [ar:]/[ti:]/[by:] header tags LRC files carry.
_LRC_TIME = re.compile(r"^\s*(?:\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]\s*)+")
_LRC_TAG = re.compile(r"^\s*\[[a-z]{2,}:[^\]]*\]\s*$", re.I)


def strip_lrc(text):
    """Plain words only, whatever the contributor actually uploaded."""
    out = []
    for line in (text or "").split("\n"):
        if _LRC_TAG.match(line):
            continue
        line = _LRC_TIME.sub("", line).rstrip()
        if line.strip():
            out.append(line)
    return "\n".join(out)


def _word_overlap(a, b):
    """Fraction of a's distinctive words that appear in b."""
    wa = [w for w in _words(a) if len(w) > 2]
    if not wa:
        return 0.0
    wb = set(_words(b))
    return sum(1 for w in wa if w in wb) / len(wa)


def belongs_to_audio(hit, yt_title):
    """Reject a hit that is a different song by the SAME artist.

    score() judges a candidate against itself, which is circular once the
    candidate is wrong: asking for "Bruno Mars" returned "Bruno Mars - Natalie
    (Official Audio)", whose name contains every word of the query, so the
    overlap gate passed it and the duration gate agreed at 225s against 236s.
    Nothing in that chain ever asked whether it was the song we separated.

    The YouTube title is the one string known to belong to this audio. So take
    the hit's own name, remove the artist's words and the usual upload junk,
    and require what is left -- the part that actually names the song -- to
    appear in it. Only a hit with nothing in common is refused, which leaves
    room for LRCLIB spelling its titles differently from the uploader.
    """
    if not yt_title:
        return True
    name = {w for w in _words(hit.get("trackName")) if len(w) > 2}
    name -= set(_words(hit.get("artistName")))
    name -= TITLE_JUNK
    if not name:
        return True
    have = set(_words(yt_title))
    return any(w in have for w in name)


def title_overlap(title, hit):
    """How much of the requested title appears in the CANDIDATE'S OWN title.

    Not in its lyrics: a Devanagari upload of the right song contains none of
    the roman title words, so testing the body would reject every correct
    Hindi result. Track names on LRCLIB are roman even when the words are not."""
    want = [w for w in _words(title) if len(w) > 2]
    if not want:
        return 0.0
    got = set(_words(hit.get("trackName")))
    return sum(1 for w in want if w in got) / len(want)


def score(hit, title, artist=None, duration=None):
    """Rank a candidate. Returns None for anything that must not be used.

    The hard gate is the title: a result whose own name shares nothing with
    what was asked for is a different song, however many lines it has. That is
    the check that would have caught Zingaat, where every candidate was a
    well-formed Devanagari song that simply was not the one requested."""
    lyr = (hit.get("plainLyrics") or "").strip()
    n = len([l for l in lyr.split("\n") if l.strip()])
    if n < 8 or is_cover(hit):
        return None
    overlap = title_overlap(title, hit)
    if overlap < 0.5:
        return None

    pts = 100 * overlap
    if script_of(lyr) == "singable":
        pts += 60
    if artist:
        want, got = set(_words(artist)), set(_words(hit.get("artistName")))
        if want & got:
            pts += 40
    if duration:
        gap = abs((hit.get("duration") or 0) - duration)
        # A hard gate, not a penalty. A modern song genuinely called "Hum Pyaar
        # Karne Wale" passes the title check outright, and its words are not
        # the ones anyone will sing — only its 3:28 against our 6:04 gives it
        # away. Two and a half minutes apart is a different recording.
        if gap > 90:
            return None
        if gap <= 20:   pts += 40
        elif gap <= 45: pts += 20
    pts += min(n, 80) / 10.0        # a fuller transcript, gently preferred
    return pts


def choose(hits, title, artist=None, duration=None):
    scored = [(score(h, title, artist, duration), h) for h in hits]
    scored = [(p, h) for p, h in scored if p is not None]
    if not scored:
        return None
    scored.sort(key=lambda t: -t[0])
    return scored[0][1]


def pick(hits):
    """Prefer an entry with real plain lyrics and the most lines — a stub of
    four lines is worse than nothing, because it looks like it worked.

    A singable script outranks line count. LRCLIB's Coke Studio uploads are
    mostly Shahmukhi: Pasoori's roman version sits at rank 10 behind nine
    identical Urdu ones, every one of them tied at 50 lines, so line count
    alone can never reach it."""
    originals = [h for h in hits if not is_cover(h)] or hits
    scored = []
    for h in originals:
        lyr = (h.get("plainLyrics") or "").strip()
        n = len([l for l in lyr.split("\n") if l.strip()])
        if n < 8:
            continue
        scored.append((script_of(lyr) == "singable", n, h))
    if not scored:
        return None
    scored.sort(key=lambda t: (0 if t[0] else 1, -t[1]))
    return scored[0][2]


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--show":
        for h in search(" ".join(args[1:])):
            print(" ", describe(h))
        return

    query, out = args[0], args[1]
    artist = duration = yt_title = None
    rest = args[2:]
    for i, a in enumerate(rest):
        if a == "--artist" and i + 1 < len(rest):
            artist = rest[i + 1]
        elif a == "--yt-title" and i + 1 < len(rest):
            yt_title = rest[i + 1]
        elif a == "--duration" and i + 1 < len(rest):
            try:
                duration = float(rest[i + 1])
            except ValueError:
                pass

    # Try the trustworthy spellings first and stop at the first that clears
    # score(). Each candidate is judged against ITSELF, so a query that finds
    # a well-formed song which is not this one still fails the overlap gate
    # and we move on rather than writing someone else's words.
    candidates = title_candidates(query, yt_title)
    best = used = None
    tried = []
    for cand in candidates:
        hits = gather(cand, artist)
        if not hits:
            tried.append(f"{cand!r} 0 hits")
            continue
        b = choose(hits, cand, artist, duration)
        if b is None:
            tried.append(f"{cand!r} {len(hits)} hits, none this song")
            continue
        if not belongs_to_audio(b, yt_title):
            tried.append(f"{cand!r} matched {b.get('trackName')!r}, "
                         f"not the song in the video title")
            continue
        best, used = b, cand
        break

    if best is None:
        for t in tried:
            print(f"  tried {t}")
        print(f"  no usable LRCLIB match for {query!r}")
        sys.exit(2 if not tried else 3)
    if used != query:
        print(f"  matched on {used!r} (asked as {query!r})")

    lyrics = strip_lrc(best["plainLyrics"]).strip()
    with open(out, "w", encoding="utf-8") as f:
        f.write(lyrics + "\n")

    # What LRCLIB actually matched, saved next to the words. The request queue
    # only ever knew what the person typed - "tu kisi raii si" - and that string
    # became the directory and therefore the title. This is the one point in the
    # pipeline that knows the song's real name, so record it here and let
    # watch-requests.py fold it into data/songs-meta.json.
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(out)), "match.json"),
                  "w", encoding="utf-8") as mf:
            json.dump({"trackName":  best.get("trackName"),
                       "artistName": best.get("artistName"),
                       "albumName":  best.get("albumName"),
                       "duration":   best.get("duration"),
                       "query":      used,
                       "ytTitle":    yt_title},
                      mf, ensure_ascii=False, indent=1)
    except Exception:
        pass          # a missing match.json must never fail a good lyrics fetch
    n = len([l for l in lyrics.split("\n") if l.strip()])
    d = best.get("duration") or 0
    print(f"  {best.get('trackName')} — {best.get('artistName')} — {n} lines"
          f" ({int(d//60)}:{int(d%60):02d}) -> {out}")


if __name__ == "__main__":
    main()
