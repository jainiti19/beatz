#!/usr/bin/env python3
"""Fold data/songs-meta.json into web/stems/songs.json.

Before this existed the player's title WAS the directory name with underscores
swapped, so a typo in a song request became the title permanently and there was
nowhere to record a singer or a film. Renaming the directory is not an option:
it keys the stems, the lyrics drop and the request queue.

Runs after prepare-web.sh has built songs.json, in the same way
check-lyrics-quality.py folds in its verdict. Songs with no metadata entry keep
the name prepare-web.sh gave them, so this is safe to run against a library
that is ahead of the metadata file.

Usage: apply-song-meta.py <web-stems-dir> [--meta data/songs-meta.json]
"""
import argparse, json, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_meta(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stems")
    ap.add_argument("--meta", default=os.path.join(REPO, "data/songs-meta.json"))
    a = ap.parse_args()

    manifest = os.path.join(a.stems, "songs.json")
    if not os.path.exists(manifest):
        sys.exit("no songs.json at " + manifest)
    if not os.path.exists(a.meta):
        print("  no metadata file, leaving titles as they are")
        return

    meta = load_meta(a.meta)
    with open(manifest, encoding="utf-8") as f:
        songs = json.load(f)

    named = 0
    tagged = 0
    untouched = []
    out = []
    for s in songs:
        m = meta.get(s["dir"])
        if not m:
            untouched.append(s["dir"])
            out.append(s)
            continue
        if m.get("hide"):
            continue                       # duplicates: kept on disk, off the screen
        if m.get("title"):
            if m["title"] != s.get("name"):
                named += 1
            s["name"] = m["title"]
        # Only write fields that carry something. An empty film is unknown, not
        # blank, and the player must be able to tell those apart to avoid
        # offering a filter chip for nothing.
        if m.get("film"):
            s["film"] = m["film"]
        if m.get("singers"):
            s["singers"] = m["singers"]
        if m.get("year"):
            s["year"] = m["year"]
        if m.get("film") or m.get("singers"):
            tagged += 1
        out.append(s)

    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")

    hidden = len(songs) - len(out)
    print(f"  metadata: {named} title(s) corrected, {tagged} tagged, "
          f"{hidden} hidden as duplicates")
    if untouched:
        print(f"  no metadata for {len(untouched)}: "
              + ", ".join(untouched[:6]) + ("..." if len(untouched) > 6 else ""))


if __name__ == "__main__":
    main()
