#!/usr/bin/env python3
"""Measure line timing against human-synced LRC files. READ-ONLY on the library
except for one additive file: <song>/lyrics_synced.lrc (the backfill).

Without a number nobody can say an aligner got better. The number here is the
distance between where an aligner starts each line and where an LRCLIB
contributor timestamped it by ear -- on the songs where their upload and ours
are the SAME CUT. That is decided by where the acoustic model hears the LRC's
own lines (align-v2.py lrc_cut(): first, middle and last third must elect the
same offset), never from either aligner's output. The timestamps themselves
stay human.

    eval-alignment.py backfill [song ...]   fetch synced lyrics for songs that
                                            lack lyrics_synced.lrc (polite: one
                                            song a second, responses cached)
    eval-alignment.py truth [song ...]      classify every song with an LRC as
                                            same-cut / different-cut / unusable
    eval-alignment.py score [--v2 DIR] [--tag NAME] [song ...]
                                            the table: library (v1) against the
                                            v2 outputs in DIR

Metric, per song, over the LRC's lines (the ground truth is the unit, so a
sung line an aligner DELETED counts as a miss, not as nothing):
    med      median |our start - LRC start| after the constant offset
    <1s <3s  share of LRC lines with one of our lines of the same text within
             1.0s / 3.0s (a missing line is outside both)
    worst    the longest contiguous run of LRC lines off by more than 3s: its
             length in seconds and where it starts
    mis      OUR lines with no same-text LRC line within 3s: words lit while
             something else, or nothing, is being sung (the precision side)
    silent   OUR lines whose span is under 25% voiced (words on a dhol break);
             this one needs no ground truth and catches surplus copies that
             the LRC-side metric cannot see

Line matching: longest in-order match between our lines and the LRC's by
normalised text (spelling-tolerant, script-tolerant), ties broken by total time
distance -- with forty "chal chaiyya"s a text-only match is ambiguous, and the
tie-break gives every aligner the benefit of the doubt equally.

The offset is fitted once per song by lrc_cut(), then refined
by the median residual of the lines that both aligners place within 1.5s of it,
so both are judged against one clock.
"""
import argparse
import difflib
import importlib.util
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser("~/Music/karaoke/htdemucs")
EVAL = os.path.expanduser("~/Music/karaoke/align-v2-eval")
HANDS_OFF = {"Aashiq_Banaya_Aapne", "Damadam_mast_kalandar"}
FRAME = 0.02

SAME_CUT_DRIFT = 1.5        # |drift| at or under this, in seconds
SAME_CUT_ON_VOICE = 0.80    # and this share of LRC line starts on our singing
TEXT_MATCH_MIN = 0.60       # backfill: share of our distinct lines the LRC carries


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_pick = None


def pick():
    global _pick
    if _pick is None:
        _pick = _load("pick_lyrics", "pick-lyrics.py")
    return _pick


# ------------------------------------------------------------------ text

_uroman = None


def skeleton(text):
    """A spelling- and script-tolerant key: romanise, drop vowels and h, squash
    doubles. 'छैय्या छैय्या' and 'chaiyya chaiyya' both come out 'cy cy'-ish."""
    global _uroman
    if any(ord(c) > 127 for c in text):
        if _uroman is None:
            import uroman as ur
            _uroman = ur.Uroman()
        text = _uroman.romanize_string(text)
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = []
    for w in re.sub(r"[^a-z\s]", " ", text).split():
        k = re.sub(r"[aeiouhy]", "", w[1:])
        k = re.sub(r"(.)\1+", r"\1", w[0] + k)
        words.append(k)
    return " ".join(words)


def norm_text(s):
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


class Keyed:
    """A line with its comparison keys computed once."""
    __slots__ = ("text", "norm", "skel")

    def __init__(self, text):
        self.text = text
        self.norm = norm_text(text)
        self.skel = skeleton(text)


def same_line(a, b):
    if a.norm == b.norm:
        return True
    if not a.skel or not b.skel:
        return False
    if a.skel == b.skel:
        return True
    sm = difflib.SequenceMatcher(None, a.skel, b.skel, autojunk=False)
    return sm.quick_ratio() >= 0.82 and sm.ratio() >= 0.82


# ------------------------------------------------------------------ audio

def voiced_for(name):
    """The aligner's voiced mask, cached (keyed on the vocals file)."""
    d = os.path.join(ROOT, name)
    vocals = os.path.join(d, "vocals.wav")
    st = os.stat(vocals)
    cdir = os.path.expanduser("~/.cache/beatznbox/voiced")
    os.makedirs(cdir, exist_ok=True)
    path = os.path.join(cdir, name + ".npz")
    if os.path.exists(path):
        try:
            z = np.load(path)
            if int(z["size"]) == st.st_size and abs(float(z["mtime"]) - st.st_mtime) < 1:
                return z["mask"].astype(bool), float(z["duration"])
        except Exception:
            pass
    a = pick().load_aligner()
    w = a.load_vocals(vocals)
    mask = a.voiced_mask(w)
    duration = w.size(1) / a.SAMPLE_RATE
    np.savez_compressed(path, mask=mask, size=st.st_size, mtime=st.st_mtime, duration=duration)
    return mask, duration


def our_texts(name):
    p = os.path.join(ROOT, name, "lyrics.txt")
    return [l.strip() for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def read_lrc(name):
    p = os.path.join(ROOT, name, "lyrics_synced.lrc")
    if not os.path.exists(p):
        return []
    return pick().parse_lrc(open(p, encoding="utf-8").read())


def cut_verdict(lrc, mask, duration):
    """same / different / unusable, from the audio alone."""
    if len(lrc) < 8:
        return "unusable", None
    s = pick().sync_agreement([t for t, _ in lrc], mask, duration)
    if not s:
        return "unusable", None
    if abs(s["drift"]) <= SAME_CUT_DRIFT and s["on_voice"] >= SAME_CUT_ON_VOICE:
        return "same", s
    return "different", s


# --------------------------------------------------------------- backfill

UA = {"User-Agent": "beatznbox/1.0 (personal singalong library)"}


def _http(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def hits_for(name):
    """LRCLIB candidates for a song dir, cached on disk so a rerun asks nothing."""
    cdir = os.path.join(EVAL, "_lrclib_cache")
    os.makedirs(cdir, exist_ok=True)
    cpath = os.path.join(cdir, name + ".json")
    if os.path.exists(cpath):
        return json.load(open(cpath, encoding="utf-8")), True
    p = pick()
    d = os.path.join(ROOT, name)
    hits = []
    mp = os.path.join(d, "match.json")
    if os.path.exists(mp):
        try:
            lid = json.load(open(mp, encoding="utf-8")).get("lrclibId")
            if lid:
                hits.append(_http(f"https://lrclib.net/api/get/{int(lid)}"))
                time.sleep(0.5)
        except Exception:
            pass
    title = p.song_title(d)
    try:
        seen = {h.get("id") for h in hits}
        for h in p.fl.gather(title):
            if h.get("id") not in seen:
                hits.append(h)
    except Exception as e:
        print(f"    search failed: {e}")
    slim = [{k: h.get(k) for k in ("id", "trackName", "artistName", "albumName", "duration",
                                   "plainLyrics", "syncedLyrics")} for h in hits]
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False)
    return slim, False


def text_match(our_lines, lrc):
    """Share of our distinct lines the LRC carries, and the reverse."""
    ours = {k.norm: k for k in map(Keyed, our_lines) if k.norm}
    theirs = {k.norm: k for k in (Keyed(b) for _, b in lrc) if k.norm}
    if not ours or not theirs:
        return 0.0, 0.0
    fwd = sum(1 for a in ours.values() if any(same_line(a, b) for b in theirs.values())) / len(ours)
    back = sum(1 for b in theirs.values() if any(same_line(a, b) for a in ours.values())) / len(theirs)
    return fwd, back


def backfill(names):
    p = pick()
    log_path = os.path.join(EVAL, "_lrc_backfill.json")
    log = json.load(open(log_path)) if os.path.exists(log_path) else {}
    for name in names:
        d = os.path.join(ROOT, name)
        if name in HANDS_OFF or not os.path.exists(os.path.join(d, "lyrics.txt")) \
                or not os.path.exists(os.path.join(d, "vocals.wav")):
            continue
        if os.path.exists(os.path.join(d, "lyrics_synced.lrc")):
            log.setdefault(name, {"status": "had one already"})
            continue
        hits, cached = hits_for(name)
        if not cached:
            time.sleep(1.0)
        ours = [l.strip() for l in open(os.path.join(d, "lyrics.txt"), encoding="utf-8") if l.strip()]
        mask, duration = voiced_for(name)
        best = None
        for h in hits:
            lrc = p.parse_lrc(h.get("syncedLyrics"))
            if len(lrc) < 8:
                continue
            fwd, back = text_match(ours, lrc)
            if fwd < TEXT_MATCH_MIN:
                continue
            verdict, s = cut_verdict(lrc, mask, duration)
            rank = (round(min(fwd, back), 1), verdict == "same", s["on_voice"] if s else 0,
                    -abs((h.get("duration") or 0) - duration))
            if best is None or rank > best[0]:
                best = (rank, h, verdict, s, fwd, back)
        if best is None:
            n_sync = sum(1 for h in hits if h.get("syncedLyrics"))
            log[name] = {"status": "no synced candidate with our words", "hits": len(hits), "synced_hits": n_sync}
            print(f"  --   {name}: {len(hits)} hits, {n_sync} synced, none carrying our words")
        else:
            _, h, verdict, s, fwd, back = best
            with open(os.path.join(d, "lyrics_synced.lrc"), "w", encoding="utf-8") as f:
                f.write(h["syncedLyrics"].strip() + "\n")
            log[name] = {"status": "written", "lrclibId": h.get("id"), "trackName": h.get("trackName"),
                         "artistName": h.get("artistName"), "duration": h.get("duration"),
                         "our_lines_found": round(fwd, 2), "their_lines_found": round(back, 2),
                         "cut": verdict, "sync": s}
            print(f"  LRC  {name}: id {h.get('id')} words {fwd:.0%}/{back:.0%} cut={verdict} "
                  f"{('off %+.1fs drift %+.1fs on-voice %.2f' % (s['offset'], s['drift'], s['on_voice'])) if s else ''}")
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=1)


# ----------------------------------------------------------------- truth

_v2 = None


def v2():
    global _v2
    if _v2 is None:
        _v2 = _load("align_v2", "align-v2.py")
    return _v2


def emission_cached(name):
    return os.path.exists(os.path.join(os.path.expanduser("~/.cache/beatznbox/emission"), name + ".pt"))


def truth(names, quiet=False):
    """same / different / unusable for every song with an LRC and a cached
    emission. The verdict is align-v2.py's lrc_cut(): every LRC line votes for
    the offsets at which the acoustic model hears ITS words, and the three
    thirds of the song must elect the same offset. (The voiced-mask fit from
    pick-lyrics.py is kept in the record for comparison; it is flat on stems
    that are voiced end to end and called Maar Daala a different cut.)

    Verdicts are cached in _truth.json, keyed on the LRC file's mtime."""
    path = os.path.join(EVAL, "_truth.json")
    known = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    out = {}
    for name in names:
        if name in HANDS_OFF:
            continue
        lp = os.path.join(ROOT, name, "lyrics_synced.lrc")
        if not os.path.exists(lp):
            continue
        if not emission_cached(name):
            out[name] = {"cut": "no emission cached"}
            continue
        stamp = os.stat(lp).st_mtime
        rec = known.get(name)
        if not rec or rec.get("lrc_mtime") != stamp or rec.get("rule") != 4 or (rec["cut"] == "different" and rec.get("map_rule") != 3):
            m = v2()
            song = m.Song(os.path.join(ROOT, name))
            lt = {}
            for _, body in song.lrc:
                w = m.al.normalize_words(body, song.dictionary)
                if w:
                    lt.setdefault(body, w)
            spots = m.spot_all(song, lt, m.PARAMS, os.path.join(m.DEFAULT_OUT, "_spots", name + ".lrc.json"))
            rec = m.lrc_cut(song, spots)
            if rec["cut"] == "different":
                # The piecewise mapping (align-v2.py lrc_map): weaker truth, since
                # each stretch's offset is fitted from the model's own hearing,
                # but the line spacing inside a stretch is still a human's.
                mp = m.lrc_map(song, spots)
                trusted = m.trusted_lines(mp)
                rec["map"] = [[o, bool(t_)] for (o, _), t_ in zip(mp, trusted)]
                rec["map_rule"] = 3
            rec["lrc_mtime"] = stamp
            rec["lrc_lines"] = len(song.lrc)
            rec["mask_fit"] = pick().sync_agreement([t for t, _ in song.lrc], song.mask, song.duration)
        out[name] = rec
        if not quiet:
            print(f"  {rec['cut']:9} {name:34} {rec.get('lrc_lines', 0):3d}L  off {rec.get('offset')}  "
                  f"thirds {rec.get('thirds')} support {rec.get('support')}")
    known.update(out)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(known, f, ensure_ascii=False, indent=1, default=float)
    if not quiet:
        n = sum(1 for v in out.values() if v["cut"] == "same")
        print(f"\n  {n} same-cut of {len(out)} songs with a synced LRC "
              f"({sum(1 for v in out.values() if v['cut'] == 'no emission cached')} lack a cached emission)")
    return out


# ----------------------------------------------------------------- score

def match_lines(ours, lrc, offset):
    """For each LRC line, the start of our matched line or None.

    Longest in-order text match; among equally long matches, the one with the
    smallest total time distance (each distance capped, so one far match cannot
    outvote many near ones)."""
    n, m = len(ours), len(lrc)
    ok = [[False] * m for _ in range(n)]
    lk = [Keyed(b) for _, b in lrc]
    cache = {}
    for i, (_, k) in enumerate(ours):
        for j in range(m):
            key = (k.norm, lk[j].norm)
            if key not in cache:
                cache[key] = same_line(k, lk[j])
            ok[i][j] = cache[key]
    CAP = 30.0
    # best[i][j] = (matches, -cost) using ours[i:], lrc[j:]
    best = [[(0, 0.0)] * (m + 1) for _ in range(n + 1)]
    move = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            a, b = best[i + 1][j], best[i][j + 1]
            choice, mv = (a, 1) if a >= b else (b, 2)
            if ok[i][j]:
                dt = min(CAP, abs(ours[i][0] - (lrc[j][0] + offset)))
                c = best[i + 1][j + 1]
                c = (c[0] + 1, c[1] - dt)
                if c >= choice:
                    choice, mv = c, 3
            best[i][j], move[i][j] = choice, mv
    got = [None] * m
    match_lines.ours_err = [None] * n          # per OUR line: signed error, or None if no LRC line took it
    i = j = 0
    while i < n and j < m:
        mv = move[i][j]
        if mv == 3:
            got[j] = ours[i][0]
            match_lines.ours_err[i] = ours[i][0] - (lrc[j][0] + offset)
            i += 1
            j += 1
        elif mv == 1:
            i += 1
        else:
            j += 1
    return got


def merge_lrc(lrc, our_texts):
    """Where OUR text writes as one line what the LRC splits in two ("Gulposh
    kabhi itraaye kahin, mehke to nazar aa jaaye kahin"), judge the pair as one
    line starting at the first timestamp. Without this the second half counts
    as a line every aligner 'missed', which says nothing about timing."""
    ours = [Keyed(t) for t in dict.fromkeys(our_texts)]
    singles = {k.norm for k in ours}
    out, j = [], 0
    while j < len(lrc):
        if j + 1 < len(lrc) and Keyed(lrc[j][1]).norm not in singles:
            both = Keyed(lrc[j][1] + " " + lrc[j + 1][1])
            if any(same_line(both, k) for k in ours) and not any(same_line(Keyed(lrc[j][1]), k) for k in ours):
                out.append((lrc[j][0], lrc[j][1] + " " + lrc[j + 1][1]))
                j += 2
                continue
        out.append(lrc[j])
        j += 1
    return out


def load_timed(path):
    if not os.path.exists(path):
        return None
    try:
        segs = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    return [s for s in segs if s.get("text") and "start" in s]


def song_metrics(segs, lrc, offset, mask):
    ours = [(s["start"], Keyed(s["text"])) for s in segs]
    got = match_lines(ours, lrc, offset)
    ours_err = list(match_lines.ours_err)
    errs = [None if g is None else g - (t + offset) for g, (t, _) in zip(got, lrc)]
    absd = [abs(e) for e in errs if e is not None]
    n = len(lrc)
    runs, cur = [], None
    for idx, e in enumerate(errs):
        bad = e is None or abs(e) > 3.0
        if bad:
            cur = [idx, idx] if cur is None else [cur[0], idx]
        elif cur is not None:
            runs.append(cur)
            cur = None
    if cur is not None:
        runs.append(cur)
    worst = (0.0, None, 0)
    for a, b in runs:
        t0 = lrc[a][0] + offset
        t1 = (lrc[b + 1][0] + offset) if b + 1 < n else lrc[b][0] + offset + 4.0
        if t1 - t0 > worst[0]:
            worst = (round(t1 - t0, 1), round(t0, 1), b - a + 1)
    silent = 0
    for s in segs:
        a, b = int(s["start"] / FRAME), max(int(s["start"] / FRAME) + 1, int(s["end"] / FRAME))
        if mask[a:b].size and mask[a:b].mean() < 0.25:
            silent += 1
    return {
        "lrc_lines": n, "matched": len(absd), "our_lines": len(segs),
        "median": round(statistics.median(absd), 2) if absd else None,
        "within1": round(100 * sum(1 for e in absd if e <= 1.0) / n, 1),
        "within3": round(100 * sum(1 for e in absd if e <= 3.0) / n, 1),
        "worst_run_sec": worst[0], "worst_run_at": worst[1], "worst_run_lines": worst[2],
        "silent_lines": silent,
        # precision: OUR lines lit within 3s of where a human put the same words.
        # The rest are words on screen while something else (or nothing) is sung.
        "placed_ok": round(100 * sum(1 for e in ours_err if e is not None and abs(e) <= 3.0) / max(1, len(segs)), 1),
        "misplaced": sum(1 for e in ours_err if e is None or abs(e) > 3.0),
        "errs": [None if e is None else round(e, 2) for e in errs],
    }


def refine_offset(offset, lrc, systems):
    """One clock for every system: the median residual of confidently matched
    lines (within 1.5s of the audio-fitted offset), pooled over the systems."""
    pool = []
    for segs in systems:
        if not segs:
            continue
        ours = [(s["start"], Keyed(s["text"])) for s in segs]
        got = match_lines(ours, lrc, offset)
        pool += [g - (t + offset) for g, (t, _) in zip(got, lrc) if g is not None and abs(g - (t + offset)) <= 1.5]
    return offset + (statistics.median(pool) if len(pool) >= 6 else 0.0)


def fmt(m):
    if not m:
        return f"{'-':>5} {'-':>5} {'-':>5} {'-':>14} {'-':>3} {'-':>3}"
    w = f"{m['worst_run_sec']:.0f}s@{m['worst_run_at']:.0f}" if m["worst_run_at"] is not None else "none"
    med = f"{m['median']:.2f}" if m["median"] is not None else "-"
    return f"{med:>5} {m['within1']:5.0f} {m['within3']:5.0f} {w:>14} {m['silent_lines']:3d} {m['misplaced']:3d}"


def mapped_lrc(name, info):
    """A different-cut LRC moved onto our clock line by line; untrusted lines dropped."""
    raw = pick().parse_lrc(open(os.path.join(ROOT, name, "lyrics_synced.lrc"), encoding="utf-8").read())
    mp = info.get("map") or []
    if len(mp) != len(raw):
        return []
    _, duration = voiced_for(name)
    return [(t + o, body) for (t, body), (o, ok) in zip(raw, mp) if ok and 0 <= t + o <= duration - 1.0]


def score(names, v2_dirs, out_json=None, include_different=False):
    tr = truth(names, quiet=True)
    rows = []
    labels = ["v1"] + [os.path.basename(d.rstrip("/")) or "v2" for d in v2_dirs]
    head = f"{'song':32} " + " | ".join(f"{l[:8]:>8}: med  <1s%  <3s%      worst-run sil mis" for l in labels)
    print(head)
    for name in names:
        info = tr.get(name)
        if not info or info["cut"] not in ("same", "different"):
            continue
        if (info["cut"] == "different") != include_different:
            continue
        if info["cut"] == "different":
            lrc = mapped_lrc(name, info)
            if len(lrc) < 12:
                continue
            lrc = merge_lrc(lrc, our_texts(name))
            info = dict(info, offset=0.0)
        else:
            lrc = merge_lrc(read_lrc(name), our_texts(name))
        mask, _ = voiced_for(name)
        systems = [load_timed(os.path.join(ROOT, name, "lyrics_timed.json"))]
        systems += [load_timed(os.path.join(d, name, "lyrics_timed.json")) for d in v2_dirs]
        offset = refine_offset(info["offset"], lrc, systems)
        ms = [song_metrics(s, lrc, offset, mask) if s else None for s in systems]
        rows.append({"song": name, "offset": round(offset, 2), "cut": info["cut"],
                     **{l: m for l, m in zip(labels, ms)}})
        print(f"{name[:32]:32} " + " | ".join(f"{'':9}{fmt(m)}" for m in ms))
    print()
    for li, l in enumerate(labels):
        have = [r for r in rows if r.get(l) and all(r.get(x) for x in labels)]
        if not have:
            continue
        tot = sum(r[l]["lrc_lines"] for r in have)
        w1 = sum(r[l]["within1"] * r[l]["lrc_lines"] for r in have) / tot
        w3 = sum(r[l]["within3"] * r[l]["lrc_lines"] for r in have) / tot
        allerr = [abs(e) for r in have for e in r[l]["errs"] if e is not None]
        print(f"  {l:10} {len(have)} songs, {tot} LRC lines: median {statistics.median(allerr):.2f}s  "
              f"within 1s {w1:.1f}%  within 3s {w3:.1f}%  "
              f"mean worst run {statistics.mean(r[l]['worst_run_sec'] for r in have):.1f}s  "
              f"silent lines {sum(r[l]['silent_lines'] for r in have)}  "
              f"misplaced lines {sum(r[l]['misplaced'] for r in have)} of {sum(r[l]['our_lines'] for r in have)}")
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    return rows


# ------------------------------------------------------------- calibrate

GRID = {
    "theta": [0.0, 0.4, 0.7, 1.0, 1.3, 1.6],
    "len_pow": [0.0, 0.5, 1.0],
    "short": [0.0, 0.5, 1.0, 2.0],
    "skip_open": [0.0, 0.5, 1.0, 2.0, 3.0],
    "skip_line": [0.0, 0.15, 0.3, 0.6, 1.0],
    "repeat": [0.5, 1.0, 1.5, 2.0, 3.0],
    "resing": [0.0, 0.5, 1.0, 1.5],
    "jump": [0.5, 1.0, 2.0, 3.0],
    "weak_z": [0.3, 0.5, 0.8, 1.2],
    "tight_hi": [1.6, 2.2, 3.0],
    "defer": [0.0, 0.1, 0.2, 0.4],
    "slack": [0.0, 0.025, 0.05, 0.1],
    "mu": [0.0, 0.5, 1.0, 2.0, 4.0],
    "stretch": [0.0, 0.5, 1.0, 2.0],
    "gain_cap": [2.0, 3.0, 4.0],
}


def calibrate(names, rounds=2, holdout=None, out_json=None):
    """Coordinate descent over align-v2's DP penalties against the same-cut
    LRC ground truth, WITHOUT the LRC prior (or it would be fitting the answer
    to itself). Objective: mean over songs of (within-1s + within-3s +
    placed-ok)/3 -- recall at two tolerances plus precision, so that lighting
    wrong words costs as much as lighting none -- each song weighing the same. Songs in `holdout` are scored but never fitted."""
    m = v2()
    tr = truth(names, quiet=True)
    data = []
    for name in names:
        info = tr.get(name)
        if not info or info.get("cut") != "same":
            continue
        song = m.Song(os.path.join(ROOT, name))
        texts = {}
        for l in song.lines:
            texts.setdefault(l["text"], l["words"])
        spots = m.spot_all(song, texts, m.PARAMS, os.path.join(m.DEFAULT_OUT, "_spots", name + ".json"))
        lrc = merge_lrc(read_lrc(name), our_texts(name))
        v1 = load_timed(os.path.join(ROOT, name, "lyrics_timed.json"))
        offset = refine_offset(info["offset"], lrc, [v1])
        data.append((name, song, spots, lrc, offset))
        print(f"  loaded {name}", flush=True)
    holdout = set(holdout or [])

    def evaluate(params, which):
        vals = []
        for name, song, spots, lrc, offset in data:
            if (name in holdout) != (which == "holdout"):
                continue
            segs, _, _ = m.align_loaded(song, spots, params)
            mm = song_metrics(segs, lrc, offset, song.mask) if segs else {"within1": 0, "within3": 0, "placed_ok": 0}
            vals.append((mm["within1"] + mm["within3"] + mm["placed_ok"]) / 3)
        return statistics.mean(vals) if vals else float("nan")

    params = dict(m.PARAMS)
    best = evaluate(params, "fit")
    print(f"  start: fit {best:.2f}  holdout {evaluate(params, 'holdout'):.2f}", flush=True)
    for r in range(rounds):
        for key, values in GRID.items():
            scores = []
            for v in values:
                scores.append((evaluate(dict(params, **{key: v}), "fit"), v))
            top = max(scores, key=lambda x: x[0])        # first best: ties go to the smaller penalty
            print(f"  round {r + 1} {key:10} " + "  ".join(f"{v}:{sc:.1f}" for sc, v in scores), flush=True)
            if top[0] > best + 0.05:
                best, params[key] = top[0], top[1]
    print(f"  final: fit {best:.2f}  holdout {evaluate(params, 'holdout'):.2f}")
    print("  " + json.dumps({k: params[k] for k in GRID}))
    if out_json:
        with open(out_json, "w") as f:
            json.dump({"params": {k: params[k] for k in GRID}, "fit": best,
                       "holdout": evaluate(params, "holdout"),
                       "fit_songs": [d[0] for d in data if d[0] not in holdout],
                       "holdout_songs": [d[0] for d in data if d[0] in holdout]}, f, indent=1)
    return params


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["backfill", "truth", "score", "calibrate"])
    ap.add_argument("--grid", help='calibrate: JSON overriding the search grid, e.g. \'{"repeat": [3, 4, 6]}\'')
    ap.add_argument("--holdout", default="", help="calibrate: comma-separated songs scored but never fitted")
    ap.add_argument("songs", nargs="*")
    ap.add_argument("--v2", action="append", default=[], help="a directory of <song>/lyrics_timed.json to compare (repeatable)")
    ap.add_argument("--json")
    ap.add_argument("--piecewise", dest="all_cuts", action="store_true",
                    help="score the DIFFERENT-cut songs instead, against their piecewise-mapped LRC (weaker truth)")
    args = ap.parse_args()
    os.makedirs(EVAL, exist_ok=True)
    names = args.songs or sorted(n for n in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, n)))
    if args.cmd == "backfill":
        backfill(names)
    elif args.cmd == "truth":
        truth(names)
    elif args.cmd == "calibrate":
        if args.grid:
            GRID.clear()
            GRID.update(json.loads(args.grid))
        calibrate(names, holdout=[x for x in args.holdout.split(",") if x], out_json=args.json)
    else:
        score(names, args.v2 or [], args.json, args.all_cuts)


if __name__ == "__main__":
    main()
