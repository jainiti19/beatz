#!/usr/bin/env python3
"""Rank every LRCLIB candidate for a song against the song's own vocals.

The top failure mode in this library is not bad timing but the WRONG WORDS: a
different rendition, another singer's version, or a full-length text against an
edited upload. fetch-lyrics-lrclib.py takes the first candidate that clears its
gates, and LRCLIB usually offers several. This tool fetches ALL of them, scores
each one against the audio we actually have, and reports a ranking with the
evidence. It is READ-ONLY unless --adopt is given, and it never adopts on its
own judgement: you name the candidate.

Evidence, cheapest first:

  synced     LRCLIB contributors often upload timestamped (LRC) lyrics. The
             timestamps belong to whichever upload they had, but once a constant
             offset is removed they matched ours to under a second on every song
             checked. So slide them over our voiced mask and ask: does every
             onset of singing in OUR stem have a line starting near it (onset
             hit), and does every line start land where someone is singing (on
             voice)? No model needed, near-ground-truth when it agrees, so it
             dominates the ranking when present. Chaiyya Chaiyya's dhol break
             (250-305s, -70 dB in the vocals stem) is where the current text
             puts nine lines and the right LRC puts none.
  aligned    Forced alignment (torchaudio MMS_FA, the model align-lyrics.py
             uses) gives a per-token Viterbi log-probability -- the "perplexity"
             of the words against the audio. Beware: it measures SPELLING as
             much as words. A hand-romanised text outscores the same words in
             Devanagari passed through uroman by 0.2-0.5, so never read a small
             score gap across scripts as evidence.
  as shipped The raw alignment is then pushed through align-lyrics.py's own
             post-passes (repeat-count correction, redistribution, re-anchoring)
             because that is what reaches the player, and the passes can add
             faults the raw path does not have: lines on silence, crushed
             lines, rushed runs, and the grade check-lyrics-quality.py would
             give. Chaiyya's nine lines in the break appear only here.

Cost. The model forward (the emission) does not depend on the text, so it is
computed ONCE per song, cached under --cache, and each candidate is then a
Viterbi pass of a couple of seconds. Scoring a song fully therefore costs one
alignment (~0.35x realtime on the laptop when idle), not one per candidate.
--windows samples N windows instead and judges each candidate by how well its
best-fitting lines sit in them (window_scores()): 3-4x cheaper on a 6-minute
song, useless on a 2-minute one (it falls back to full), and blind to surplus
lines and missing sections, which the whole-song metrics catch. Use it to
triage a library, --full to decide a song.

Usage:
    pick-lyrics.py <song_dir> --full            # rank on the whole song
    pick-lyrics.py <song_dir> --windows 3       # sampled (default when neither given)
    pick-lyrics.py <song_dir> --title "Real Title"
    pick-lyrics.py <song_dir> --dump DIR        # write each candidate's timed lines
    pick-lyrics.py <song_dir> --json report.json
    pick-lyrics.py <song_dir> --adopt <lrclib id>   # write the named candidate

--adopt backs up lyrics.txt and lyrics_timed.json (.precandidate.bak, never
overwritten), writes lyrics.txt, lyrics_synced.lrc and match.json, then reruns
align-lyrics.py --force so lyrics_timed.json is rebuilt by the real pipeline.
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE = os.path.expanduser("~/.cache/beatznbox/emission")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fl = _load("fetch_lyrics_lrclib", "fetch-lyrics-lrclib.py")
quality = _load("check_lyrics_quality", "check-lyrics-quality.py")
al = None          # align-lyrics.py imports torch; loaded lazily


FRAME = 0.02                 # voiced_mask() frame, seconds
SILENT_LINE = 0.25           # a line whose span is < this fraction voiced is "on silence"
SYNC_TOL = 0.6               # a line start within this of voiced audio is "on voice"
ONSET_TOL = 1.0              # an onset with a line start within this is "hit"
MIN_BLOCK = 3.0              # voiced passages at least this long
OFFSET_RANGE = 90.0          # constant offset searched between LRCLIB's upload and ours
FIT_SCORE = -2.0             # a line scoring above this is confidently placed (library-wide)


def load_aligner():
    global al
    if al is None:
        al = _load("align_lyrics", "align-lyrics.py")
    return al


# ----------------------------------------------------------------- candidates

_TS = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text):
    """[(seconds, line text)] for every timestamped, non-empty line."""
    out = []
    for raw in (text or "").split("\n"):
        stamps = _TS.findall(raw)
        if not stamps or fl._LRC_TAG.match(raw):
            continue
        body = _TS.sub("", raw).strip()
        if not body:
            continue
        for m, s, frac in stamps:
            t = int(m) * 60 + int(s) + (int(frac.ljust(3, "0")) / 1000 if frac else 0)
            out.append((t, body))
    out.sort(key=lambda x: x[0])
    return out


def norm_text(s):
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def lines_of(plain):
    return [l.strip() for l in fl.strip_lrc(plain).split("\n") if l.strip()]


def sync_times_for(lines, lrc):
    """Per line, the LRC timestamp with the same text (repeats consumed in
    order); None when the synced text does not carry that line."""
    pool = {}
    for t, body in lrc:
        pool.setdefault(norm_text(body), []).append(t)
    out = []
    for l in lines:
        ts = pool.get(norm_text(l))
        out.append(ts.pop(0) if ts else None)
    return out


def song_title(song_dir, override=None):
    if override:
        return override
    mp = os.path.join(song_dir, "match.json")
    if os.path.exists(mp):
        try:
            t = json.load(open(mp, encoding="utf-8")).get("trackName")
            if t:
                return fl._tidy(t) or t          # 'X (From "Dil")' -> 'X'
        except Exception:
            pass
    meta = os.path.join(HERE, "..", "data", "songs-meta.json")
    name = os.path.basename(song_dir.rstrip("/"))
    if os.path.exists(meta):
        try:
            m = json.load(open(meta, encoding="utf-8"))
            entry = m.get(name) if isinstance(m, dict) else None
            if isinstance(entry, dict) and entry.get("title"):
                return fl._tidy(entry["title"]) or entry["title"]
        except Exception:
            pass
    return name.replace("_", " ")


def gather_candidates(song_dir, title, duration, max_gap):
    """Every LRCLIB hit for the title plus what we have on disk, de-duplicated
    by text. Hits fetch-lyrics-lrclib.py would refuse outright (cover markers,
    under 8 lines, no title overlap, duration off by more than max_gap,
    translations) are listed as rejected and not scored."""
    hits = fl.gather(title)
    cands, rejected, seen = [], [], {}
    for h in hits:
        plain = (h.get("plainLyrics") or "").strip()
        lines = lines_of(plain)
        gap = abs((h.get("duration") or 0) - duration)
        why = None
        if len(lines) < 8:
            why = "under 8 lines"
        elif fl.is_cover(h):
            why = "cover/remix by title"
        elif fl.title_overlap(title, h) < 0.5:
            why = "title does not match"
        elif gap > max_gap:
            why = f"duration off by {gap:.0f}s"
        elif fl.looks_foreign(plain) > 0.04:
            why = "looks like a translation"
        if why:
            rejected.append((h, why))
            continue
        key = norm_text("\n".join(lines))
        lrc = parse_lrc(h.get("syncedLyrics"))
        c = {
            "id": str(h.get("id")),
            "trackName": h.get("trackName"), "artistName": h.get("artistName"),
            "albumName": h.get("albumName"), "duration": h.get("duration"),
            "gap": round(gap, 1), "lines": lines, "plain": plain,
            "lrc": lrc, "synced_text": (h.get("syncedLyrics") or "").strip(),
            "script": quality.script_of(plain), "dupes": [],
        }
        if key in seen:
            prev = seen[key]
            # Same words already listed: keep the copy with timestamps and the
            # closer duration; remember the other id so the report shows it.
            if (bool(c["lrc"]), -gap) > (bool(prev["lrc"]), -prev["gap"]):
                c["dupes"] = prev["dupes"] + [prev["id"]]
                cands[cands.index(prev)] = c
                seen[key] = c
            else:
                prev["dupes"].append(c["id"])
            continue
        seen[key] = c
        cands.append(c)

    current = None
    lp = os.path.join(song_dir, "lyrics.txt")
    if os.path.exists(lp):
        plain = open(lp, encoding="utf-8").read()
        lines = [l.strip() for l in plain.split("\n") if l.strip()]
        sp = os.path.join(song_dir, "lyrics_synced.lrc")
        lrc = parse_lrc(open(sp, encoding="utf-8").read()) if os.path.exists(sp) else []
        mj = {}
        mp = os.path.join(song_dir, "match.json")
        if os.path.exists(mp):
            try:
                mj = json.load(open(mp, encoding="utf-8"))
            except Exception:
                mj = {}
        current = {
            "id": "current", "trackName": mj.get("trackName") or "(lyrics.txt)",
            "artistName": mj.get("artistName") or "", "albumName": mj.get("albumName"),
            "duration": mj.get("duration"),
            "gap": round(abs((mj.get("duration") or duration) - duration), 1),
            "lines": lines, "plain": plain, "lrc": lrc, "synced_text": "",
            "script": quality.script_of(plain), "dupes": [], "lrclibId": mj.get("lrclibId"),
        }
        key = norm_text("\n".join(lines))
        for c in cands:
            if norm_text("\n".join(c["lines"])) == key:
                current["same_as"] = c["id"]
                if not current["lrc"]:
                    current["lrc"] = c["lrc"]
                break
    return cands, current, rejected, len(hits)


# ----------------------------------------------------------------- audio side

def _runs(mask):
    """[(i0, i1)] frame index runs where mask is True."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def bridged(mask, gap=0.4):
    """The mask with gaps shorter than `gap` seconds filled: a breath is not a
    break."""
    m = mask.copy()
    runs = _runs(mask)
    for (a0, a1), (b0, b1) in zip(runs, runs[1:]):
        if (b0 - a1) * FRAME < gap:
            m[a1:b0] = True
    return m


def voiced_blocks(mask, min_len=MIN_BLOCK):
    """[(t0, t1)] continuous voiced passages at least min_len seconds long."""
    return [(i0 * FRAME, i1 * FRAME) for i0, i1 in _runs(bridged(mask))
            if (i1 - i0) * FRAME >= min_len]


def onsets(mask, min_len=1.0, min_gap=0.5):
    """Seconds at which singing starts after a real gap: where a synced
    lyric's line must start too, if it is the same rendition."""
    runs = _runs(bridged(mask))
    out, prev_end = [], -1e9
    for i0, i1 in runs:
        if (i1 - i0) * FRAME >= min_len and (i0 - prev_end) * FRAME >= min_gap:
            out.append(i0 * FRAME)
        prev_end = i1
    return np.array(out, dtype=float)


def voiced_fraction(mask, t0, t1):
    a, b = int(t0 / FRAME), max(int(t0 / FRAME) + 1, int(t1 / FRAME))
    a, b = max(0, a), min(len(mask), b)
    return float(mask[a:b].mean()) if b > a else 0.0


def sync_agreement(lrc_times, mask, duration):
    """How well a candidate's timestamps fit OUR singing after removing the
    constant offset between its upload and ours. None without timestamps.

      offset     seconds added to the candidate's times to fit our audio
      onset_hit  share of our singing onsets with a line start within ONSET_TOL
                 (a section the words lack, or a rendition with a different
                 structure, leaves onsets with no line)
      onset_gap  median distance from an onset to the nearest line start
      on_voice   share of line starts landing on voiced audio (+-SYNC_TOL);
                 lines the recording never sings land on silence
      drift      offset fitted on the last third of onsets minus the first
                 third, each held within 8s of the global fit; beyond ~3s it
                 is a different master, not a trimmed intro
    """
    times = np.array([t for t in lrc_times if t is not None], dtype=float)
    ons = onsets(mask)
    if len(times) < 4 or len(ons) < 3:
        return None
    n = len(mask)
    k = int(SYNC_TOL / FRAME)
    dil = np.convolve(mask.astype(np.int8), np.ones(2 * k + 1, dtype=np.int8), "same") > 0

    def gaps(on, off):
        return np.abs(on[:, None] - (times + off)[None, :]).min(axis=1)

    def on_voice_at(off, ts=times):
        idx = ((ts + off) / FRAME).astype(int)
        inside = (idx >= 0) & (idx < n)
        return float(dil[idx[inside]].mean() * inside.mean()) if inside.any() else 0.0

    def line_onset_hit(off, ts=times):
        """Share of LINE starts within ONSET_TOL of one of our onsets."""
        return float((np.abs((ts + off)[:, None] - ons[None, :]).min(axis=1) <= ONSET_TOL).mean())

    # Both terms are anchored on the candidate's lines, never on our onsets:
    # a stem that carries humming or a flute the separator left in has
    # onsets no text covers, and fitting to those pulled Agar Tum Mil Jao's
    # offset to -61s when 0s was right.
    def cost(on, off, ts=times):
        return (1 - on_voice_at(off, ts)) + 0.5 * (1 - line_onset_hit(off, ts))

    def fit(ts, lo, hi, step):
        grid = np.arange(lo, hi + step / 2, step)
        return float(min(grid, key=lambda o: cost(ons, o, ts)))

    coarse = fit(times, -OFFSET_RANGE, OFFSET_RANGE, 0.25)
    best = fit(times, coarse - 1, coarse + 1, 0.05)
    g = gaps(ons, best)
    on_voice = on_voice_at(best)
    # Drift: the first and last third of the LINES fitted on their own, each
    # free to sit anywhere in the search range. An edited upload shows here
    # as tens of seconds (Agar Tum Mil Jao: +0.4s at the start, -77s at the
    # end, a verse and an interlude cut from the 6:00 album version).
    third = len(times) // 3
    drift = 0.0
    if third >= 4:
        drift = fit(times[-third:], -OFFSET_RANGE, OFFSET_RANGE, 0.25) - fit(times[:third], -OFFSET_RANGE, OFFSET_RANGE, 0.25)
    return {
        "offset": round(best, 2),
        "onset_hit": round(float((g <= ONSET_TOL).mean()), 3),
        "onset_gap": round(float(np.median(g)), 2),
        "on_voice": round(on_voice, 3),
        "drift": round(float(drift), 1),
        "n_lines": int(len(times)), "n_onsets": int(len(ons)),
    }


# --------------------------------------------------------------- alignment

def emission_for(song_dir, waveform, cache_dir):
    """Frame posteriors for the whole song, computed once and cached, keyed on
    the vocals file's size and mtime so a re-separated song is recomputed."""
    a = load_aligner()
    import torch
    vocals = os.path.join(song_dir, "vocals.wav")
    st = os.stat(vocals)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, os.path.basename(song_dir.rstrip("/")) + ".pt")
    if os.path.exists(path):
        try:
            blob = torch.load(path)
            if blob.get("size") == st.st_size and abs(blob.get("mtime", 0) - st.st_mtime) < 1:
                return blob["emission"].float(), True
        except Exception:
            pass
    model, _ = a.get_model()
    t = time.time()
    em = a.compute_emission(model, waveform)
    torch.save({"emission": em.half(), "size": st.st_size, "mtime": st.st_mtime,
                "seconds": round(time.time() - t, 1)}, path)
    return em, False


def line_words(lines, dictionary):
    a = load_aligner()
    out = []
    for text in lines:
        w = a.normalize_words(text, dictionary)
        if w:
            out.append({"text": text, "words": w})
    return out


def align_lines(emission, line_list, dictionary, seconds_per_frame):
    """Exactly align-lyrics.py's build_segments(): stars between, before and
    after the lines, so unsung audio is absorbed rather than forced."""
    a = load_aligner()
    units = [("star", [dictionary["*"]])]
    for idx, line in enumerate(line_list):
        if idx:
            units.append(("star", [dictionary["*"]]))
        for word in line["words"]:
            units.append(("word", [dictionary[c] for c in word]))
    units.append(("star", [dictionary["*"]]))
    return a._regroup(a.align(emission, units, dictionary), line_list, seconds_per_frame)


def as_shipped(emission, waveform, line_list, dictionary, spf):
    """What align-lyrics.py would write for these words: its post-passes run
    over the raw alignment, in its order. Returns (segments, note)."""
    a = load_aligner()
    lines = list(line_list)

    def build(ll):
        return align_lines(emission, ll, dictionary, spf)

    segs = build(lines)
    note = ""
    # The passes narrate every decision on stdout; that is align-lyrics.py's
    # log, not this report's.
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            proposals = a.correct_repeat_counts(waveform, lines, segs, spf)
            corrected = a.verify_repeat_counts(lines, segs, proposals, build)
            if corrected:
                lines = corrected
                segs = build(lines)
                note = f"repeat pass {len(line_list)}->{len(lines)} lines"
        except Exception as e:
            note = f"repeat pass failed: {type(e).__name__}"
        if not segs:
            return [], note
        segs = a.redistribute_repeats(segs)
        segs = a.reanchor_outliers(segs)
        segs = a.reanchor_outliers(a.clamp_held_words(segs))
    for s in segs:
        if s["end"] <= s["start"]:
            s["end"] = round(s["start"] + 0.5, 2)
    return segs, note


def grade_segments(segs):
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "lyrics_timed.json"), "w", encoding="utf-8") as f:
            json.dump(segs, f, ensure_ascii=False)
        g = quality.grade(d)
    return g[0] + (f" ({g[1]})" if g[1] else "")


def timing_metrics(segs, mask):
    """Faults a listener would meet, measured on any timed line list."""
    if not segs:
        return None
    durs = [s["end"] - s["start"] for s in segs]
    silent = sum(1 for s in segs if voiced_fraction(mask, s["start"], s["end"]) < SILENT_LINE)
    return {
        "lines": len(segs),
        "silent_lines": silent, "silent_frac": round(silent / len(segs), 3),
        "crushed_pct": round(100 * sum(1 for d in durs if d < quality.CRUSHED_SEC) / len(durs), 1),
        "rushed_run": quality.rushed_run(segs),
        "longest": round(max(durs), 1),
        "median_score": round(statistics.median(s["score"] for s in segs if "score" in s), 3) if segs else None,
        "grade": grade_segments(segs),
    }


def raw_metrics(segs, mask, n_lines):
    """Whole-song evidence from the raw alignment of the candidate."""
    if not segs:
        return None
    word_scores = [w["score"] for s in segs for w in s["words"]]
    cover = np.zeros(len(mask), dtype=bool)
    for s in segs:
        a, b = int((s["start"] - 0.3) / FRAME), int((s["end"] + 0.3) / FRAME)
        cover[max(0, a):max(0, b)] = True
    voiced_total = int(mask.sum())
    m = timing_metrics(segs, mask)
    m.update({
        "word_score": round(statistics.mean(word_scores), 3),
        "voiced_coverage": round(float((cover & mask).sum() / voiced_total), 3) if voiced_total else 0.0,
        "source_lines": n_lines,
        "span": (round(segs[0]["start"], 1), round(segs[-1]["end"], 1)),
    })
    return m


SURPLUS_RUN = 3              # consecutive lines that make a block, not a blemish
SURPLUS_SCORE = 2.5          # points under the song's median line score


def surplus_blocks(segs, mask):
    """Runs of >= SURPLUS_RUN consecutive lines the raw alignment could not
    find: each scores SURPLUS_SCORE under the song's median AND is either
    crammed (3x the median word rate) or parked on silence or held past 12s.

    This is the "full-length text against an edited upload" failure. Agar
    Tum Mil Jao's 4:34 edit drops the second verse of the 6:00 album cut;
    the 11 lines of that verse scored -5.5 to -6.5 against a median of -0.6
    and were crammed into the interlude at 154-188s, dragging the highlight
    16s ahead of the singer (reported by ear, 21 Sep 2026). Everything else
    in the song scored under -3.1. Returns [(first_idx, last_idx)] over segs.
    """
    if len(segs) < 2 * SURPLUS_RUN:
        return []
    scores = [s["score"] for s in segs]
    rates = [len(s["words"]) / max(0.05, s["end"] - s["start"]) for s in segs]
    med_score, med_rate = statistics.median(scores), statistics.median(rates)

    def low(i):
        return scores[i] <= med_score - SURPLUS_SCORE

    def misplaced(i):
        s = segs[i]
        return (rates[i] > 3 * med_rate or voiced_fraction(mask, s["start"], s["end"]) < SILENT_LINE
                or s["end"] - s["start"] > 12)

    # The run is defined by SCORE alone: a line the singer never sang scores
    # badly wherever the Viterbi path parks it, and parking is what varies --
    # in Agar's block, six lines were crammed, one was held 18s over the
    # interlude and four sat at a plausible rate on the humming between,
    # which broke a timing-only run into pieces. The timing test then asks
    # that at least half the run is visibly misplaced, so three consecutive
    # lines a backing choir sings badly do not get cut.
    blocks, i = [], 0
    while i < len(segs):
        if low(i):
            j = i
            while j < len(segs) and low(j):
                j += 1
            if j - i >= SURPLUS_RUN and sum(1 for k in range(i, j) if misplaced(k)) * 2 >= j - i:
                blocks.append((i, j - 1))
            i = j
        else:
            i += 1
    return blocks


def derive_trimmed(cand, segs, mask):
    """A candidate made from `cand` with its surplus blocks removed, or None.
    Its id is '<id>~trim' so --adopt can name it; the dropped lines are kept
    on the candidate for the report and for match.json."""
    blocks = surplus_blocks(segs, mask)
    if not blocks:
        return None
    drop_text = set()
    dropped = []
    for i0, i1 in blocks:
        for k in range(i0, i1 + 1):
            dropped.append((k, segs[k]["text"]))
    # segs index lines that had alignable words, which is cand["lines"] minus
    # any line normalize_words() emptied; map back through the text in order.
    keep, di, drop_idx = [], 0, {k for k, _ in dropped}
    seg_i = 0
    for line in cand["lines"]:
        if seg_i < len(segs) and norm_text(segs[seg_i]["text"]) == norm_text(line):
            if seg_i in drop_idx:
                seg_i += 1
                continue
            seg_i += 1
        keep.append(line)
    if len(keep) < 8 or len(keep) == len(cand["lines"]):
        return None
    c = dict(cand)
    c.update({"id": cand["id"] + "~trim", "lines": keep, "plain": "\n".join(keep),
              "dupes": [], "dropped": dropped, "derived_from": cand["id"],
              "trackName": (cand["trackName"] or "") + " (trimmed)"})
    c.pop("same_as", None)
    return c


def sync_vs_aligned(segs, lines, sync_times, offset):
    """Median gap between where WE aligned a line and where the contributor
    timestamped it (after the offset). Under ~1.5s means the words are the
    ones being sung there."""
    by_text = {}
    for l, t in zip(lines, sync_times):
        if t is not None:
            by_text.setdefault(norm_text(l), []).append(t + offset)
    gaps = []
    for s in segs:
        ts = by_text.get(norm_text(s["text"]))
        if ts:
            gaps.append(abs(s["start"] - ts.pop(0)))
    if not gaps:
        return None
    return {"median_gap": round(statistics.median(gaps), 2),
            "within_2s": round(sum(1 for g in gaps if g <= 2) / len(gaps), 3), "n": len(gaps)}


# ---------------------------------------------------------------- windows

def choose_windows(blocks, duration, n, length):
    """n windows of `length` seconds from different parts of the sung audio:
    the voiced span is cut into n equal parts and each window opens at the
    first voiced passage inside its part."""
    if not blocks:
        return [(i * duration / n, min(duration, i * duration / n + length)) for i in range(n)]
    lo, hi = blocks[0][0], blocks[-1][1]
    out = []
    for i in range(n):
        p0, p1 = lo + (hi - lo) * i / n, lo + (hi - lo) * (i + 1) / n
        starts = [b0 for b0, _ in blocks if p0 <= b0 < p1]
        t0 = max(0.0, min(starts[0] if starts else p0, duration - length))
        out.append((t0, min(duration, t0 + length)))
    return out


def window_emissions(waveform, windows):
    """The emission for each window alone, with 2s of context either side
    (discarded), as compute_emission() pads its chunks."""
    a = load_aligner()
    import torch
    model, _ = a.get_model()
    sr = a.SAMPLE_RATE
    out = []
    for t0, t1 in windows:
        lo, hi = max(0, int((t0 - 2) * sr)), min(waveform.size(1), int((t1 + 2) * sr))
        with torch.inference_mode():
            em, _ = model(waveform[:, lo:hi])
        spf = (hi - lo) / sr / em.size(1)
        drop_lo = int((int(t0 * sr) - lo) / sr / spf)
        keep = max(1, round((t1 - t0) / spf))
        out.append((em[:, drop_lo:drop_lo + keep], spf))
    return out


def window_scores(cand, wems, windows, mask, dictionary, top_k=8):
    """Best-fit line scan. In each window every DISTINCT line of the candidate
    is aligned on its own (stars either side) and the best top_k line scores
    are averaged: the right words have about top_k lines that sit well in any
    40s of singing, the wrong rendition has few. `fitting` counts the lines
    placed above FIT_SCORE. Hundreds of tiny Viterbi passes, ~2ms each."""
    seen, distinct = set(), []
    for l in cand["lines"]:
        k = norm_text(l)
        if k and k not in seen:
            seen.add(k)
            distinct.append(l)
    ll = line_words(distinct, dictionary)
    per_window = []
    for (em, spf), (t0, t1) in zip(wems, windows):
        scores = []
        for line in ll:
            if len(line["words"]) < 2:
                continue
            segs = align_lines(em, [line], dictionary, spf)
            if segs:
                s = segs[0]
                vf = voiced_fraction(mask, t0 + s["start"], t0 + s["end"])
                scores.append(s["score"] if vf >= SILENT_LINE else s["score"] - 2.0)
        scores.sort(reverse=True)
        top = scores[:top_k]
        per_window.append({"window": (round(t0, 1), round(t1, 1)),
                           "top_k_mean": round(statistics.mean(top), 3) if top else None,
                           "fitting": sum(1 for s in scores if s > FIT_SCORE)})
    tops = [w["top_k_mean"] for w in per_window if w["top_k_mean"] is not None]
    return {"word_score": round(statistics.mean(tops), 3) if tops else None,
            "fitting_lines": sum(w["fitting"] for w in per_window),
            "windows": per_window}


# ------------------------------------------------------------------ ranking

def composite(c):
    """One number to sort by, built from the printed evidence so a reader can
    see why. Synced agreement dominates when present."""
    m = c.get("metrics") or {}
    sh = c.get("shipped") or {}
    pts = 0.0
    if m.get("word_score") is not None:
        pts += 40 * m["word_score"]                    # per-token log-prob, ~-1..-5
    if "voiced_coverage" in m:
        pts += 60 * m["voiced_coverage"]
    t = sh or m
    if "silent_frac" in t:
        pts += 60 * (1 - t["silent_frac"]) - t["crushed_pct"] - 3 * t["rushed_run"]
    if "fitting_lines" in m:
        pts += 2 * m["fitting_lines"]
    s = c.get("sync")
    if s:
        pts += 60 * s["onset_hit"] + 40 * s["on_voice"]
        if abs(s["drift"]) > 3:
            pts -= 20
    sa = c.get("sync_vs_aligned")
    if sa:
        pts += 30 * sa["within_2s"]
    pts -= (c.get("gap") or 0) / 10
    return round(pts, 1)


def clear_win(winner, current):
    """The adoption rule: better alignment score AND fewer lines on silence
    (as shipped) AND, where both carry timestamps, better agreement."""
    if current is None or winner is current:
        return False, "winner is what we have"
    wm, cm = winner.get("metrics") or {}, current.get("metrics") or {}
    if wm.get("word_score") is None or cm.get("word_score") is None:
        return False, "no alignment score to compare"
    ok, reasons = True, []
    if wm["word_score"] > cm["word_score"]:
        reasons.append(f"score {wm['word_score']} > {cm['word_score']}")
    else:
        ok = False
        reasons.append(f"score {wm['word_score']} not better than {cm['word_score']}"
                       + (" (different script: spelling, not words)" if winner["script"] != current["script"] else ""))
    ws_, cs_ = winner.get("shipped") or wm, current.get("shipped") or cm
    if "silent_lines" in ws_ and "silent_lines" in cs_:
        if ws_["silent_lines"] < cs_["silent_lines"]:
            reasons.append(f"silent lines {ws_['silent_lines']} < {cs_['silent_lines']}")
        elif ws_["silent_lines"] == cs_["silent_lines"] == 0:
            reasons.append("silent lines 0 = 0")
        else:
            ok = False
            reasons.append(f"silent lines {ws_['silent_lines']} not fewer than {cs_['silent_lines']}")
    # A text that leaves singing uncovered is missing lines, however well
    # the lines it has score. Aaj Jaane Ki Zid Na Karo's 47-line candidate
    # scored better than the 55-line text on disk and left five 10s
    # passages of singing dark that the longer text carries.
    if "voiced_coverage" in wm and "voiced_coverage" in cm:
        if wm["voiced_coverage"] < cm["voiced_coverage"] - 0.05:
            ok = False
            reasons.append(f"covers less of the singing ({wm['voiced_coverage']:.2f} vs {cm['voiced_coverage']:.2f})")
    ws, cs = winner.get("sync"), current.get("sync")
    if ws and cs and (abs(ws["drift"]) > 10 or abs(cs["drift"]) > 10):
        reasons.append("timestamps are from a different cut (drift > 10s), not compared")
    elif ws and cs:
        if (ws["onset_hit"], ws["on_voice"]) > (cs["onset_hit"], cs["on_voice"]):
            reasons.append(f"sync onset-hit {ws['onset_hit']} vs {cs['onset_hit']}")
        else:
            ok = False
            reasons.append(f"sync onset-hit {ws['onset_hit']} not better than {cs['onset_hit']}")
    elif ws and not cs:
        reasons.append(f"winner has timestamps (onset-hit {ws['onset_hit']}, on-voice {ws['on_voice']}), current has none")
    return ok, "; ".join(reasons)


def fmt_sync(s):
    if not s:
        return "no timestamps"
    return (f"sync onset-hit {s['onset_hit']:.2f} (gap {s['onset_gap']:.1f}s) on-voice {s['on_voice']:.2f} "
            f"off {s['offset']:+.1f}s drift {s['drift']:+.1f}s")


def fmt_row(c, mode):
    m = c.get("metrics") or {}
    sh = c.get("shipped")
    tag = c["id"] + ("=" + c["same_as"] if c.get("same_as") else "")
    dupes = f" (+{len(c['dupes'])} same text)" if c.get("dupes") else ""
    head = (f"  {c['composite']:7.1f}  {tag:>10}  {str(c['trackName'])[:26]:26} {str(c['artistName'])[:18]:18} "
            f"{len(c['lines']):3d}L d{c['gap']:+4.0f}s {c['script'][:4]}{dupes}")
    if mode == "full" and m:
        ev = (f"raw: score {m['word_score']:.3f}  silent {m['silent_lines']}/{m['lines']}  "
              f"cover {m['voiced_coverage']:.2f}")
        sa = c.get("sync_vs_aligned")
        if sa:
            ev += f"  sync-vs-aligned {sa['median_gap']:.1f}s ({sa['within_2s']:.0%} within 2s)"
        if sh:
            ev += (f"\n            shipped: {sh['lines']}L silent {sh['silent_lines']}  crushed {sh['crushed_pct']:.0f}%  "
                   f"rushed {sh['rushed_run']}  longest {sh['longest']:.0f}s  grade {sh['grade']}"
                   + (f"  [{c['shipped_note']}]" if c.get("shipped_note") else ""))
    elif m:
        ev = f"windows: score {m['word_score'] if m['word_score'] is not None else '-'}  fitting {m['fitting_lines']}"
    else:
        ev = "(not scored)"
    if c.get("dropped"):
        ks = [k for k, _ in c["dropped"]]
        ev += (f"\n            dropped {len(ks)} unsung lines ({ks[0] + 1}-{ks[-1] + 1} of {c['derived_from']}): "
               + " / ".join(t[:22] for _, t in c["dropped"][:4]) + (" ..." if len(ks) > 4 else ""))
    return f"{head}\n            {ev}\n            {fmt_sync(c.get('sync'))}"


# ------------------------------------------------------------------- adopt

def backup(path, suffix=".precandidate.bak"):
    if os.path.exists(path) and not os.path.exists(path + suffix):
        shutil.copy2(path, path + suffix)


def adopt(song_dir, cand, title):
    lp = os.path.join(song_dir, "lyrics.txt")
    tp = os.path.join(song_dir, "lyrics_timed.json")
    backup(lp)
    backup(tp)
    with open(lp, "w", encoding="utf-8") as f:
        f.write("\n".join(cand["lines"]) + "\n")
    sp = os.path.join(song_dir, "lyrics_synced.lrc")
    if cand["synced_text"]:
        with open(sp, "w", encoding="utf-8") as f:
            f.write(cand["synced_text"] + "\n")
    elif os.path.exists(sp):
        os.remove(sp)
    mp = os.path.join(song_dir, "match.json")
    mj = {}
    if os.path.exists(mp):
        try:
            mj = json.load(open(mp, encoding="utf-8"))
        except Exception:
            mj = {}
    base = cand.get("derived_from") or cand["id"]
    mj.update({"trackName": (cand["trackName"] or "").replace(" (trimmed)", ""),
               "artistName": cand["artistName"],
               "albumName": cand["albumName"], "duration": cand["duration"],
               "lrclibId": int(base) if base.isdigit() else base,
               "synced": bool(cand["synced_text"]), "query": title,
               "pickedBy": "pick-lyrics.py"})
    if cand.get("dropped"):
        mj["trimmedLines"] = [t for _, t in cand["dropped"]]
    else:
        mj.pop("trimmedLines", None)
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(mj, f, ensure_ascii=False, indent=1)
    print(f"  wrote lyrics.txt ({len(cand['lines'])} lines), "
          f"{'lyrics_synced.lrc, ' if cand['synced_text'] else ''}match.json; realigning...")
    r = subprocess.run([sys.executable, os.path.join(HERE, "align-lyrics.py"), song_dir, "--force"])
    if r.returncode != 0:
        print("  align-lyrics.py failed; lyrics_timed.json.precandidate.bak holds the old timings")
        return False
    return True


def roman_coverage(song_dir):
    """How many aligned words carry a reviewed romanisation, and how many
    Devanagari lines have none (those need romanize-new.py)."""
    tp = os.path.join(song_dir, "lyrics_timed.json")
    rp = os.path.join(song_dir, "roman.json")
    if not os.path.exists(tp):
        return None
    segs = json.load(open(tp, encoding="utf-8"))
    have = set()
    if os.path.exists(rp):
        try:
            have = {norm_text(l["text"]) for l in json.load(open(rp, encoding="utf-8")).get("lines", [])}
        except Exception:
            pass
    covered = sum(len(s.get("words", [])) for s in segs if norm_text(s["text"]) in have)
    dev_unrom = sum(1 for s in segs if quality.script_of(s["text"]) == "devanagari"
                    and norm_text(s["text"]) not in have)
    return {"roman_words": covered, "words": sum(len(s.get("words", [])) for s in segs),
            "devanagari_lines_unromanised": dev_unrom}


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("song_dir")
    ap.add_argument("--title", help="LRCLIB query; default from match.json / songs-meta.json / dir name")
    ap.add_argument("--full", action="store_true", help="score on the whole song (emission cached)")
    ap.add_argument("--windows", type=int, default=3, help="sampled windows when not --full (default 3)")
    ap.add_argument("--window-len", type=float, default=40.0)
    ap.add_argument("--max-gap", type=float, default=90.0, help="reject candidates this far off in duration")
    ap.add_argument("--limit", type=int, default=12, help="score at most this many distinct candidates")
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--json", help="write the report here as JSON")
    ap.add_argument("--dump", help="write each candidate's timed lines (raw and as shipped) into this dir")
    ap.add_argument("--adopt", metavar="ID", help="write this candidate's words and realign (never automatic)")
    args = ap.parse_args()

    song_dir = os.path.abspath(args.song_dir)
    name = os.path.basename(song_dir)
    vocals = os.path.join(song_dir, "vocals.wav")
    if not os.path.exists(vocals):
        sys.exit(f"no vocals.wav in {song_dir}")

    a = load_aligner()
    waveform = a.load_vocals(vocals)
    duration = waveform.size(1) / a.SAMPLE_RATE
    mask = a.voiced_mask(waveform)
    blocks = voiced_blocks(mask)
    ons = onsets(mask)
    title = song_title(song_dir, args.title)
    print(f"{name}: {duration:.0f}s, {int(mask.sum()) * FRAME:.0f}s voiced in {len(blocks)} passages, "
          f"{len(ons)} onsets; LRCLIB query {title!r}")

    cands, current, rejected, n_hits = gather_candidates(song_dir, title, duration, args.max_gap)
    print(f"  {n_hits} hits, {len(cands)} distinct usable texts, {len(rejected)} rejected"
          + (f"; current lyrics.txt {'= candidate ' + current['same_as'] if current.get('same_as') else 'not on LRCLIB verbatim'}"
             if current else "; no lyrics.txt"))
    for h, why in rejected[:8]:
        print(f"    rejected: {why:28} {fl.describe(h)}")
    if len(rejected) > 8:
        print(f"    ... {len(rejected) - 8} more rejected")

    # What is on disk right now, graded against the same mask.
    shipped_now = None
    tp = os.path.join(song_dir, "lyrics_timed.json")
    if os.path.exists(tp):
        try:
            shipped_now = timing_metrics(json.load(open(tp, encoding="utf-8")), mask)
        except Exception:
            shipped_now = None
    if shipped_now:
        print(f"  on disk: {shipped_now['lines']}L silent {shipped_now['silent_lines']}  crushed {shipped_now['crushed_pct']:.0f}%  "
              f"rushed {shipped_now['rushed_run']}  longest {shipped_now['longest']:.0f}s  grade {shipped_now['grade']}")

    # Synced agreement first: no model needed, so every candidate gets it.
    for c in cands + ([current] if current else []):
        c["sync_times"] = sync_times_for(c["lines"], c["lrc"]) if c["lrc"] else [None] * len(c["lines"])
        c["sync"] = sync_agreement(c["sync_times"], mask, duration)

    cands.sort(key=lambda c: -composite(c))
    to_score = cands[:args.limit] + ([current] if current else [])
    skipped = cands[args.limit:]

    model, dictionary = a.get_model()
    mode = "full" if args.full else "windows"
    if mode == "windows":
        windows = choose_windows(blocks, duration, args.windows, args.window_len)
        if sum(t1 - t0 for t0, t1 in windows) > 0.6 * duration:
            print(f"  windows would cover most of a {duration:.0f}s song; scoring in full instead")
            mode = "full"
    t0 = time.time()
    if mode == "full":
        emission, cached = emission_for(song_dir, waveform, args.cache)
        spf = duration / emission.size(1)
        print(f"  emission {'from cache' if cached else 'computed'} in {time.time() - t0:.0f}s")

        def score_full(c):
            ll = line_words(c["lines"], dictionary)
            segs = align_lines(emission, ll, dictionary, spf)
            c["metrics"] = raw_metrics(segs, mask, len(c["lines"]))
            c["segments_raw"] = segs
            if c["sync"]:
                c["sync_vs_aligned"] = sync_vs_aligned(segs, c["lines"], c["sync_times"], c["sync"]["offset"])
            shipped, note = as_shipped(emission, waveform, ll, dictionary, spf)
            c["shipped"] = timing_metrics(shipped, mask)
            c["shipped_note"] = note
            c["segments_shipped"] = shipped
            return segs

        derived = []
        for c in to_score:
            segs = score_full(c)
            # A text with a block the recording never sings gets a second
            # chance without it. Only the on-disk text and its LRCLIB twin are
            # worth it: trimming a wrong rendition still leaves a wrong one.
            if c is current or (current and c["id"] == current.get("same_as")):
                t = derive_trimmed(c, segs, mask)
                if t and not any(d["lines"] == t["lines"] for d in derived):
                    t["sync_times"] = sync_times_for(t["lines"], t["lrc"]) if t["lrc"] else [None] * len(t["lines"])
                    t["sync"] = sync_agreement(t["sync_times"], mask, duration)
                    score_full(t)
                    derived.append(t)
        to_score += derived
        cands += derived
    else:
        wems = window_emissions(waveform, windows)
        print(f"  {len(windows)} windows " + ", ".join(f"{w0:.0f}-{w1:.0f}s" for w0, w1 in windows)
              + f" ({sum(w1 - w0 for w0, w1 in windows) / duration:.0%} of the song), forward {time.time() - t0:.0f}s")
        for c in to_score:
            c["metrics"] = window_scores(c, wems, windows, mask, dictionary)
    elapsed = time.time() - t0

    for c in to_score:
        c["composite"] = composite(c)
    ranked = sorted(to_score, key=lambda c: -c["composite"])
    print(f"\n  ranking ({mode}, {elapsed:.0f}s):")
    for c in ranked:
        print(fmt_row(c, mode))
    for c in skipped:
        print(f"  (not scored, pre-rank {composite(c):.0f}) {c['id']} {c['trackName']} {c['artistName']} {len(c['lines'])}L")

    winner = ranked[0]
    is_current = lambda c: c is current or (current is not None and c["id"] == current.get("same_as"))
    best_new = next((c for c in ranked if not is_current(c)), None)
    if current is None:
        print(f"\n  no lyrics.txt; best candidate {winner['id']} ({winner['trackName']} - {winner['artistName']})")
    elif is_current(winner):
        print("\n  verdict: KEEP - what we have ranks first")
        if best_new:
            print(f"           runner-up {best_new['id']} {best_new['trackName']} - {best_new['artistName']}")
    else:
        ok, why = clear_win(winner, current)
        print(f"\n  verdict: {'CLEAR' if ok else 'NOT CLEAR'} - candidate {winner['id']} "
              f"({winner['trackName']} - {winner['artistName']}, {len(winner['lines'])}L) vs current: {why}")
        print(f"           adopt with: pick-lyrics.py {args.song_dir} --adopt {winner['id']}")

    if args.dump:
        os.makedirs(args.dump, exist_ok=True)
        for c in ranked:
            for kind in ("segments_raw", "segments_shipped"):
                if c.get(kind):
                    with open(os.path.join(args.dump, f"{name}.{c['id']}.{kind[9:]}.json"), "w", encoding="utf-8") as f:
                        json.dump(c[kind], f, ensure_ascii=False, indent=1)

    if args.json:
        drop = {"segments_raw", "segments_shipped", "plain", "synced_text", "lrc", "sync_times", "lines"}
        rep = {"song": name, "title": title, "mode": mode, "duration": round(duration, 1),
               "voiced_seconds": round(float(mask.sum()) * FRAME, 1), "blocks": len(blocks), "onsets": len(ons),
               "hits": n_hits, "elapsed": round(elapsed, 1), "on_disk": shipped_now,
               "candidates": [{k: v for k, v in c.items() if k not in drop} | {"n_lines": len(c["lines"])} for c in ranked],
               "rejected": [{"id": h.get("id"), "trackName": h.get("trackName"), "why": why} for h, why in rejected]}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)

    if args.adopt:
        pick = next((c for c in cands if c["id"] == args.adopt and c is not current), None)
        if pick is None:
            sys.exit(f"  no candidate with id {args.adopt!r}")
        if pick.get("dropped") and pick.get("derived_from") == "current" and not pick["synced_text"]:
            sp = os.path.join(song_dir, "lyrics_synced.lrc")
            if os.path.exists(sp):
                pick["synced_text"] = open(sp, encoding="utf-8").read().strip()
        before = roman_coverage(song_dir)
        print(f"\n  adopting {pick['id']} ({pick['trackName']} - {pick['artistName']})")
        if adopt(song_dir, pick, title):
            after = roman_coverage(song_dir)
            g = quality.grade(song_dir)
            print(f"  grade now: {g[0]} {g[1]}".rstrip())
            print(f"  roman words: {before['roman_words'] if before else '-'} -> {after['roman_words']} of {after['words']}; "
                  f"{after['devanagari_lines_unromanised']} Devanagari lines without reviewed spelling"
                  + (" (run romanize-new.py)" if after['devanagari_lines_unromanised'] else ""))


if __name__ == "__main__":
    main()
