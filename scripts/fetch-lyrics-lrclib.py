#!/usr/bin/env python3
"""Fetch lyrics from LRCLIB.

Genius returns nothing usable for classic Hindi film songs — wrong song, or a
transliteration nobody sings from. LRCLIB is community-synced karaoke data, so
it covers Bollywood well and often carries per-line timings already.

We take only the words. Timing comes from align-lyrics.py, which solves against
this song's actual audio; LRCLIB's own timings are for whichever upload the
contributor had, which is rarely the same cut.

Usage:
    fetch-lyrics-lrclib.py "song name" out.txt        # search and write
    fetch-lyrics-lrclib.py --show "song name"         # list candidates only
"""
import json, sys, urllib.parse, urllib.request

API = "https://lrclib.net/api/search"
UA = {"User-Agent": "beatznbox/1.0 (personal singalong library)"}


def search(query, limit=20):
    url = f"{API}?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        hits = json.load(r)
    return hits[:limit]


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
    hits = search(query)
    if not hits:
        print(f"  no LRCLIB match for {query!r}")
        sys.exit(2)
    best = pick(hits)
    if best is None:
        print(f"  only stub results for {query!r} ({len(hits)} hits, all under 8 lines)")
        sys.exit(3)

    lyrics = best["plainLyrics"].strip()
    with open(out, "w", encoding="utf-8") as f:
        f.write(lyrics + "\n")
    n = len([l for l in lyrics.split("\n") if l.strip()])
    print(f"  {best.get('trackName')} — {best.get('artistName')} — {n} lines -> {out}")


if __name__ == "__main__":
    main()
