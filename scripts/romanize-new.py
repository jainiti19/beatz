#!/usr/bin/env python3
"""Fill in readable romanised spellings for songs that only have uroman's.

The `A` toggle in the player shows one romanised word per aligned word. uroman
produces those by rule, so they read "mujhako itanaa bataae koii" where the room
expects "mujhko itna bataye koi". Every Devanagari song in the library was fixed
by hand (well, by agent) -- and then every NEW song arrived with uroman again,
because nothing in the pipeline did it. Iti hit that twice in a week.

So this asks `claude -p` for the spellings, one song at a time, and is safe to
run unattended:

  * the model never touches a file. It answers with a JSON array of arrays and
    THIS script writes roman.json, so a confused answer cannot corrupt timings.
  * the token count of every line must match the aligned word count exactly,
    or the song is left on uroman. romanize-lyrics.py apply enforces it again.
  * a song that already has reviewed spellings is skipped, so re-running is
    free and cannot overwrite anyone's corrections.

Usage:
  romanize-new.py <stems_dir> [more dirs...]   romanise these songs
  romanize-new.py --all <htdemucs_dir>         every song still on uroman
  romanize-new.py --dry-run ...                say what would be done
"""

import json
import os
import re
import subprocess
import sys

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MODEL = os.environ.get("BEATZ_ROMAN_MODEL", "claude-sonnet-5")
TIMEOUT = int(os.environ.get("BEATZ_ROMAN_TIMEOUT", "300"))
HERE = os.path.dirname(os.path.abspath(__file__))

# The house style, in the owner's words: "chahat should be chahat and not
# caaht". Kept here rather than in the prompt string below so it reads as a
# rule of the project and not as one agent's taste.
STYLE = """Romanise Hindi/Urdu/Punjabi song lyrics the everyday way Indians type them
on YouTube lyric videos. Lowercase. Drop doubled vowels that only mirror the
Devanagari matra: chaahat->chahat, dekhaa->dekha, itanaa->itna, mujhako->mujhko,
koii->koi, jiine->jeene, hamem->humein, karataa->karta, naa->na, kii->ki,
huaa->hua, gayaa->gaya. KEEP the doubling where that is the usual spelling: aaj,
aankh, aaya, yaad, pyaar, yaar, saath, baat, raat, haath, jaan, jaana, khwaab,
chaand, saamne, kaash, naam, saara. Use sh/ch/kh/gh, z for ज़, w for व in woh and
wafa. Spell a word the same way everywhere in the song. Sargam syllables stay as
notes (pa dha pa, ga ma ga re)."""


def needs_work(stems_dir):
    """A song needs romanising when its aligned words are Devanagari and at
    least one carries no reviewed spelling."""
    path = os.path.join(stems_dir, "lyrics_timed.json")
    if not os.path.exists(path):
        return False
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return False
    words = [w for line in data if isinstance(line, dict) for w in line.get("words", [])]
    if not words:
        return False
    if not any(DEVANAGARI.search(line.get("text", "")) for line in data):
        return False
    return any(not w.get("roman") for w in words)


def ask_model(job):
    """One song, one call. The answer is data, never a file edit."""
    lines = [{"n": i, "text": l["text"], "tokens": l["tokens"]}
             for i, l in enumerate(job["lines"])]
    prompt = (
        STYLE
        + "\n\nBelow is a JSON array of lines. Each has the Devanagari text and the "
        "aligned word tokens as the aligner split them (they may be odd -- they come "
        "from a machine transliteration). For EACH line return the romanised spelling "
        "of each token, in the same order.\n\n"
        "Answer with JSON ONLY, no prose and no code fence: an array of objects "
        '{"n": <the line number>, "roman": ["word", ...]}. The roman array MUST have '
        "exactly as many strings as that line's tokens array. Never merge, split, add "
        "or drop a token -- each one carries a timing.\n\n"
        + json.dumps(lines, ensure_ascii=False)
    )
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", MODEL],
        capture_output=True, text=True, timeout=TIMEOUT,
    )
    if out.returncode != 0:
        raise RuntimeError(f"claude exited {out.returncode}: {out.stderr.strip()[:200]}")
    text = out.stdout.strip()
    # Tolerate a code fence even though the prompt forbids one.
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise RuntimeError(f"no JSON in the answer: {text[:200]}")
    return json.loads(m.group(0))


def romanize(stems_dir, dry_run=False):
    name = os.path.basename(stems_dir.rstrip("/"))
    if not needs_work(stems_dir):
        return "skip"
    if dry_run:
        print(f"  would romanise {name}")
        return "dry"

    job_path = os.path.join(stems_dir, "roman.json")
    subprocess.run([sys.executable, os.path.join(HERE, "romanize-lyrics.py"),
                    "dump", stems_dir], check=True, capture_output=True)
    job = json.load(open(job_path, encoding="utf-8"))
    todo = [l for l in job["lines"] if not l.get("roman")]
    if not todo:
        return "skip"

    try:
        answer = ask_model(job)
    except Exception as e:
        print(f"  {name}: left on uroman ({type(e).__name__}: {e})")
        return "fail"

    by_n = {a.get("n"): a.get("roman") for a in answer if isinstance(a, dict)}
    filled = 0
    for i, line in enumerate(job["lines"]):
        roman = by_n.get(i)
        # The count is the whole safety story: a line that does not match is
        # left alone rather than pairing words with someone else's timings.
        if not isinstance(roman, list) or len(roman) != len(line["tokens"]):
            continue
        if any(not isinstance(r, str) or not r.strip() for r in roman):
            continue
        line["roman"] = [r.strip() for r in roman]
        filled += 1

    if filled < len(job["lines"]):
        print(f"  {name}: {filled}/{len(job['lines'])} lines answered usably")
    if not filled:
        return "fail"

    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
    apply = subprocess.run([sys.executable, os.path.join(HERE, "romanize-lyrics.py"),
                            "apply", stems_dir], capture_output=True, text=True)
    print("  " + (apply.stdout.strip() or apply.stderr.strip()))
    return "ok" if apply.returncode == 0 else "fail"


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--all":
        root = args[1] if len(args) > 1 else os.path.expanduser("~/Music/karaoke/htdemucs")
        dirs = sorted(os.path.join(root, d) for d in os.listdir(root)
                      if os.path.isdir(os.path.join(root, d)))
    else:
        dirs = args

    counts = {}
    for d in dirs:
        r = romanize(d, dry_run=dry)
        counts[r] = counts.get(r, 0) + 1
    done = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"romanize-new: {done or 'nothing to do'}")
    # A failure here must never fail a publish: the song still plays, and its
    # words still show, just in the machine spelling.
    sys.exit(0)


if __name__ == "__main__":
    main()
