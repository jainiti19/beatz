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
Jo Muskura Rahe Ho" 20). Nothing here fixes that, and deliberately so: searching
shorter and shorter prefixes of the title DOES find hits, but they are other
songs ("Hum pyaar karne wale" -> "I'm coming in to get my shits"). Wrong lyrics
that look right are worse than none — see the Zingaat case in the project
notes — so a candidate must earn its place, and no-result is an honest answer.

Usage:
    fetch-lyrics-lrclib.py "song name" out.txt              # search and write
    fetch-lyrics-lrclib.py "song name" out.txt --artist X   # X ranks, never filters
    fetch-lyrics-lrclib.py "song name" out.txt --duration 275
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
    artist = duration = None
    rest = args[2:]
    for i, a in enumerate(rest):
        if a == "--artist" and i + 1 < len(rest):
            artist = rest[i + 1]
        elif a == "--duration" and i + 1 < len(rest):
            try:
                duration = float(rest[i + 1])
            except ValueError:
                pass

    hits = gather(query, artist)
    if not hits:
        print(f"  no LRCLIB match for {query!r}")
        sys.exit(2)
    best = choose(hits, query, artist, duration)
    if best is None:
        print(f"  {len(hits)} results for {query!r}, none of them this song")
        sys.exit(3)

    lyrics = best["plainLyrics"].strip()
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
                       "duration":   best.get("duration")},
                      mf, ensure_ascii=False, indent=1)
    except Exception:
        pass          # a missing match.json must never fail a good lyrics fetch
    n = len([l for l in lyrics.split("\n") if l.strip()])
    d = best.get("duration") or 0
    print(f"  {best.get('trackName')} — {best.get('artistName')} — {n} lines"
          f" ({int(d//60)}:{int(d%60):02d}) -> {out}")


if __name__ == "__main__":
    main()
