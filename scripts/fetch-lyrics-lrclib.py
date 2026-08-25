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


def search(query, limit=6):
    url = f"{API}?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        hits = json.load(r)
    return hits[:limit]


def describe(h):
    dur = h.get("duration") or 0
    lyr = h.get("plainLyrics") or ""
    n = len([l for l in lyr.split("\n") if l.strip()])
    return (f"{h.get('trackName','?')[:38]:40} {h.get('artistName','?')[:22]:24} "
            f"{int(dur//60)}:{int(dur%60):02d}  {n:3d} lines"
            f"{'  [synced]' if h.get('syncedLyrics') else ''}")


def pick(hits):
    """Prefer an entry with real plain lyrics and the most lines — a stub of
    four lines is worse than nothing, because it looks like it worked."""
    scored = []
    for h in hits:
        lyr = (h.get("plainLyrics") or "").strip()
        n = len([l for l in lyr.split("\n") if l.strip()])
        if n < 8:
            continue
        scored.append((n, h))
    if not scored:
        return None
    scored.sort(key=lambda t: -t[0])
    return scored[0][1]


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
