#!/usr/bin/env python3
"""
Replace uroman's mechanical transliteration with readable romanised Hindi.

The `A` toggle in the player shows the aligner's own tokens, because those are
the only strings carrying per-word timings. uroman builds them by rule, so they
read "mujhako itanaa bataae koii" where a singer expects "mujhko itna bata de
koi" — unreadable at tempo, which defeats the toggle's whole purpose.

This does NOT touch alignment. It adds a `roman` key beside each word's `word`,
`start` and `end`, so timings and the word-level sweep are untouched and the
player falls back to `word` wherever `roman` is missing.

  dump  <stems_dir> [job.json]   write the job: each distinct line, its uroman
                                 tokens, and a null `roman` for a human or an
                                 agent to fill in. Defaults to <stems_dir>/roman.json.
  apply <stems_dir> [job.json]   write `roman` back into lyrics_timed.json.

Entries are keyed by **line text, not line index**. Indices are not stable —
correct_repeat_counts() rewrites how many times a line appears, so a realign
renumbers everything. The text is stable, and identical text normalises to
identical tokens, so one entry correctly serves every repetition of a line.
That also makes the job re-appliable: realign, then apply the same roman.json.
"""

import json
import os
import shutil
import sys


def timed_path(stems_dir):
    return os.path.join(stems_dir, "lyrics_timed.json")


def default_job(stems_dir):
    return os.path.join(stems_dir, "roman.json")


def load_timed(stems_dir):
    path = timed_path(stems_dir)
    if not os.path.exists(path):
        sys.exit(f"no lyrics_timed.json in {stems_dir}")
    return path, json.load(open(path, encoding="utf-8"))


def cmd_dump(stems_dir, out_path):
    _, data = load_timed(stems_dir)

    existing = {}
    if os.path.exists(out_path):
        try:
            for e in json.load(open(out_path, encoding="utf-8"))["lines"]:
                if e.get("roman"):
                    existing[e["text"]] = e["roman"]
        except Exception:
            pass

    seen, job = set(), []
    for line in data:
        words = line.get("words") or []
        text = line.get("text", "")
        if not words or text in seen:
            continue
        seen.add(text)
        tokens = [w["word"] for w in words]
        prior = existing.get(text)
        job.append({
            "text": text,
            "tokens": tokens,
            # Carry forward anything already answered, but only if it still fits:
            # a realign can change a line's token count if its lyrics.txt changed.
            "roman": prior if prior and len(prior) == len(tokens) else None,
        })

    payload = {"song": os.path.basename(stems_dir.rstrip("/")), "lines": job}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    todo = sum(1 for l in job if not l["roman"])
    print(f"{payload['song']}: {len(job)} distinct lines "
          f"({todo} to fill), {sum(len(l['tokens']) for l in job)} tokens -> {out_path}")
    return todo


def cmd_apply(stems_dir, job_path):
    path, data = load_timed(stems_dir)
    if not os.path.exists(job_path):
        sys.exit(f"no job file at {job_path} -- run `dump` first")
    job = json.load(open(job_path, encoding="utf-8"))

    # Validate the whole job before writing anything. A half-applied file leaves
    # some lines readable and some not, with nothing on disk saying which.
    table = {}
    for entry in job["lines"]:
        roman = entry.get("roman")
        if not roman:
            continue
        if len(roman) != len(entry["tokens"]):
            sys.exit(f"{entry['text'][:40]!r}: {len(roman)} roman tokens for "
                     f"{len(entry['tokens'])} aligned words -- counts must match "
                     f"so every token keeps its timing\n"
                     f"  aligned: {entry['tokens']}\n  roman:   {roman}")
        if any(not isinstance(r, str) or not r.strip() for r in roman):
            sys.exit(f"{entry['text'][:40]!r}: empty token in {roman}")
        table[entry["text"]] = [r.strip() for r in roman]

    if not table:
        sys.exit("nothing to apply -- every line's `roman` is still null")

    hit = miss = 0
    for line in data:
        words = line.get("words") or []
        roman = table.get(line.get("text", ""))
        # Guard the count again at the point of use: a line's token list can
        # differ from the job's if lyrics.txt was edited after the dump.
        if not roman or len(roman) != len(words):
            miss += len(words)
            continue
        for w, r in zip(words, roman):
            w["roman"] = r
        hit += len(words)

    bak = path + ".preroman.bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    name = os.path.basename(stems_dir.rstrip("/"))
    print(f"{name}: {hit} tokens romanised, {miss} left on uroman")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("dump", "apply"):
        sys.exit(__doc__)
    mode, stems = sys.argv[1], sys.argv[2]
    job = sys.argv[3] if len(sys.argv) > 3 else default_job(stems)
    (cmd_dump if mode == "dump" else cmd_apply)(stems, job)
