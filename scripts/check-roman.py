#!/usr/bin/env python3
"""Validate romanisation job files without touching lyrics_timed.json.

The apply step refuses a token-count mismatch, because a roman list that is a
different length from the aligned words would silently pair words with the
wrong timings. This says so before anything is written.

Usage: check-roman.py <stems_dir> [more dirs...]
"""
import json, os, sys

bad = filled = total = 0
for d in sys.argv[1:]:
    job = os.path.join(d, "roman.json")
    if not os.path.exists(job):
        print(f"MISSING roman.json: {d}")
        bad += 1
        continue
    data = json.load(open(job, encoding="utf-8"))
    for e in data["lines"]:
        total += 1
        r = e.get("roman")
        if not r:
            continue
        filled += 1
        if not isinstance(r, list):
            print(f"{data['song']}: roman is not a list for {e['text'][:30]!r}")
            bad += 1
        elif len(r) != len(e["tokens"]):
            print(f"{data['song']}: {len(r)} roman vs {len(e['tokens'])} tokens"
                  f"  {e['text'][:34]!r}\n    tokens: {e['tokens']}\n    roman:  {r}")
            bad += 1
        elif any((not isinstance(x, str)) or not x.strip() for x in r):
            print(f"{data['song']}: empty token in {r}")
            bad += 1
print(f"\n{filled}/{total} lines filled across {len(sys.argv)-1} songs; {bad} problem(s)")
sys.exit(1 if bad else 0)
