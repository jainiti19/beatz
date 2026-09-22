#!/usr/bin/env python3
"""align-v2: local scoring + a line-level matching DP, instead of one global
forced alignment.

WHY. align-lyrics.py (v1) runs ONE Viterbi pass of the whole text over the whole
song. That assumes text and audio correspond one to one, and wherever they do
not -- a verse the upload cut, a hook the source under-counted, an alaap no text
covers, thirty seconds of intro -- the path has nowhere to put the mismatch, so
it smears it over the neighbouring lines. Every v1 post-pass is a repair for one
shape of that smear. v2 makes the mismatch a first-class move instead.

HOW.
  1 audio     sung passages from the vocal stem's voiced mask; ARTICULATION MASS
              (the model's per-frame P(not blank): words have it, an alaap or a
              held note does not); syllable pulses of the loudness envelope.
  2 spotting  for every DISTINCT line, slide a short window over the cached
              emission and force-align the line alone inside it (stars either
              side; a small per-frame charge on blanks inside the line keeps it
              compact). ~0.2ms a pass, two passes (generous windows, then
              windows barely longer than the line so eight hooks running are
              eight placements, not two). Each placement's score is v1's own
              statistic -- mean per-token Viterbi log-probability, Vibhor's
              per-word perplexity made local -- turned into z: how far above
              this line's own null (its fit to singing that is not it), in null
              inter-quartile ranges. One scale for a studio vocal and a 1964
              mono film track alike.
  3 matching  a DP over (line just sung, furthest line sung so far), monotonic
              in TIME, with explicit moves into line j at a placement:
                next     j = i+1                           free
                skip     new lines never sung              skip_open + skip_line each (affine:
                                                           a cut verse is one event)
                defer    new lines passed over, but the gap before this placement
                         HAS ROOM for them (voiced seconds >= room x what they need):
                         probably sung where the model is deaf; defer each + slack
                return   back to the frontier after a repeat   free
                repeat   j <= i (the audio decides the count)   repeat + resing per line
                jump     i+1 < j <= frontier                    jump + resing
              and mu per second of articulation mass no line claims. A
              placement earns (z - theta), scaled by line length; short lines
              must clear a higher bar; stretched placements are charged.
  4 prior     lyrics_synced.lrc. SAME CUT (first/middle/last third of its lines
              elect one offset, no stretch dissents): each line is pulled to
              its timestamp, and a timestamp the model cannot confirm becomes a
              placement in its own right. DIFFERENT CUT: a Viterbi over the
              LRC's lines finds the piecewise offset map (Agar Tum Mil Jao:
              +0.5s, then -77s after the verse our upload drops); only
              well-supported stretches are used as prior.
  5 words     word times from a local alignment inside each matched line's own
              slot, bounded by its neighbours: an error cannot leave its gap.
  6 gap fill  lines the DP deferred: identical neighbours exchange places;
              weak placements inside the pinned gap are accepted in order;
              lines with no evidence at all are laid in only where the gap holds
              about the singing they need AND enough syllable pulses.
  7 report    skipped lines, repeats, and voiced islands >4s nothing claimed,
              each labelled from its articulation mass, the best any-line fit
              there, and the lyric lines skipped around it.

SAFETY. Reads the library, writes ONLY under --out (default
~/Music/karaoke/align-v2-eval/<song>/). Adoption is a separate decision.

Usage:
    align-v2.py <song_dir>... [--out DIR] [--no-lrc] [--emit-only] [--dump]
"""
import argparse
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.expanduser("~/Music/karaoke/align-v2-eval")
HANDS_OFF = {"Aashiq_Banaya_Aapne", "Damadam_mast_kalandar"}
FRAME = 0.02                       # voiced-mask frame, seconds


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pick = _load("pick_lyrics", "pick-lyrics.py")      # emission cache, LRC parsing, offset fit
al = pick.load_aligner()                           # align-lyrics.py: model, tokens, voiced mask

import torch                                       # noqa: E402  (after the aligner, which sets it up)
import torchaudio.functional as AF                 # noqa: E402

torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))


# -------------------------------------------------------------------- text

_uroman = None


def skeleton(text):
    """Spelling- and script-tolerant key for comparing OUR line with an LRC's:
    romanise, drop vowels/h/y after the first letter, squash doubles. (Same
    rule as eval-alignment.py, copied so neither script imports the other.)"""
    global _uroman
    if any(ord(c) > 127 for c in text):
        if _uroman is None:
            import uroman as ur
            _uroman = ur.Uroman()
        text = _uroman.romanize_string(text)
    import unicodedata
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    out = []
    for w in re.sub(r"[^a-z\s]", " ", text).split():
        k = re.sub(r"[aeiouhy]", "", w[1:])
        out.append(re.sub(r"(.)\1+", r"\1", w[0] + k))
    return " ".join(out)


def same_text(a, b):
    import difflib
    if pick.norm_text(a) == pick.norm_text(b):
        return True
    ka, kb = skeleton(a), skeleton(b)
    if not ka or not kb:
        return False
    return ka == kb or difflib.SequenceMatcher(None, ka, kb, autojunk=False).ratio() >= 0.82


# ------------------------------------------------------------------ inputs

class Song:
    """Everything v2 reads about one song. Nothing here writes."""

    def __init__(self, song_dir, cache_dir=pick.DEFAULT_CACHE, need_emission=True):
        self.dir = os.path.abspath(song_dir)
        self.name = os.path.basename(self.dir.rstrip("/"))
        self.dictionary = al.bundle.get_dict(star="*")       # the model itself loads only on a cache miss
        self.star = self.dictionary["*"]
        vocals = os.path.join(self.dir, "vocals.wav")
        waveform = al.load_vocals(vocals)
        self.duration = waveform.size(1) / al.SAMPLE_RATE
        self.mask = al.voiced_mask(waveform)
        # Syllable pulses: peaks of the stem's loudness envelope. Chanting has
        # three or four a second; a held note or an alaap has one.
        hop = int(FRAME * al.SAMPLE_RATE)
        power = (waveform[0] ** 2).unsqueeze(0).unsqueeze(0)
        db = 20 * torch.log10(torch.sqrt(torch.nn.functional.avg_pool1d(power, hop, hop)).squeeze() + 1e-10).numpy()
        sm = np.convolve(db, np.ones(3) / 3, "same")
        n = len(sm)
        peak = np.zeros(n, dtype=bool)
        for i in range(6, n - 3):
            if sm[i] >= sm[i - 3:i + 4].max() and sm[i] - sm[max(0, i - 8):i].min() >= 4.0 and sm[i] > db.max() - 35:
                peak[i] = True
        self.pulse_cum = np.concatenate([[0], np.cumsum(peak)])
        self.voiced_cum = np.concatenate([[0.0], np.cumsum(self.mask) * FRAME])
        self.emission = None
        if need_emission:
            em, self.cached = pick.emission_for(self.dir, waveform, cache_dir)
            self.emission = em
            self.T = em.size(1)
            self.spf = self.duration / self.T
            # P(some token, not blank) per frame: "is anyone articulating here".
            # Its running sum is the song's ARTICULATION MASS: seconds' worth of
            # frames the model believes carry a consonant or vowel of some word.
            # An alaap, a hum, a held note and instrument bleed are voiced but
            # carry almost none; bols and unlisted words carry plenty. The DP
            # charges for unclaimed MASS, not unclaimed voiced seconds.
            self.nonblank = 1.0 - em[0, :, 0].exp().numpy()
            idx = np.minimum(len(self.mask) - 1, (np.arange(self.T) * self.spf / FRAME).astype(int))
            self.mass_cum = np.concatenate([[0.0], np.cumsum(self.nonblank * self.mask[idx]) * self.spf])
        raw = [l.strip() for l in open(os.path.join(self.dir, "lyrics.txt"), encoding="utf-8").read().split("\n")]
        self.lines = []
        for text in raw:
            if not text:
                continue
            words = al.normalize_words(text, self.dictionary)
            if words:
                self.lines.append({"text": text, "words": words})
        sp = os.path.join(self.dir, "lyrics_synced.lrc")
        self.lrc = pick.parse_lrc(open(sp, encoding="utf-8").read()) if os.path.exists(sp) else []

    def mass(self, t0, t1):
        """Articulation mass between two times, in seconds."""
        a = min(self.T, max(0, int(round(t0 / self.spf))))
        b = min(self.T, max(a, int(round(t1 / self.spf))))
        return float(self.mass_cum[b] - self.mass_cum[a])

    def pulses(self, t0, t1):
        a = min(len(self.pulse_cum) - 1, max(0, int(t0 / FRAME)))
        b = min(len(self.pulse_cum) - 1, max(a, int(t1 / FRAME)))
        return int(self.pulse_cum[b] - self.pulse_cum[a])

    def voiced(self, t0, t1):
        """Voiced seconds between two times."""
        a = min(len(self.mask), max(0, int(round(t0 / FRAME))))
        b = min(len(self.mask), max(a, int(round(t1 / FRAME))))
        return float(self.voiced_cum[b] - self.voiced_cum[a])


# ---------------------------------------------------------------- spotting

def tokens_of(words, dictionary, star):
    return [star] + [dictionary[c] for w in words for c in w] + [star]


def place(song, words, f0, f1, targets=None):
    """Force-align one line alone inside frames [f0, f1), stars either side.

    Returns (score, start_s, end_s, word_spans) where score is the line's mean
    per-word, per-token Viterbi log-probability -- the same statistic v1 stores
    as `score`, so the library's numbers carry over -- or None if the window is
    too short to hold the tokens."""
    if targets is None:
        targets = torch.tensor([tokens_of(words, song.dictionary, song.star)], dtype=torch.int32)
    n_tok = targets.size(1)
    f0, f1 = max(0, f0), min(song.T, f1)
    if f1 - f0 < 2 * n_tok + 2:
        return None
    try:
        aligned, scores = AF.forced_align(song.emission[:, f0:f1], targets, blank=0)
    except Exception:
        return None
    p = aligned[0].numpy()
    sc = scores[0].numpy()
    change = np.flatnonzero(np.diff(p, prepend=-1) != 0)
    run_end = np.append(change[1:], len(p))
    keep = p[change] != 0
    starts, ends = change[keep], run_end[keep]
    if len(starts) != n_tok:
        return None
    cs = np.concatenate([[0.0], np.cumsum(sc)])
    means = (cs[ends] - cs[starts]) / (ends - starts)
    starts, ends, means = starts[1:-1], ends[1:-1], means[1:-1]      # drop the stars
    spans, k = [], 0
    for w in words:
        n = len(w)
        spans.append(((f0 + starts[k]) * song.spf, (f0 + ends[k + n - 1]) * song.spf,
                      float(means[k:k + n].mean())))
        k += n
    score = float(np.mean([s[2] for s in spans]))
    return score, spans[0][0], spans[-1][1], spans


def window_seconds(words):
    """Long enough to hold the line sung slowly, short enough to stay local."""
    chars = sum(len(w) for w in words)
    return float(min(24.0, max(8.0, 4.0 + 0.4 * chars)))


def spot(song, words, hop=1.0, win=None, found=None):
    """Every distinct place this line fits: {(start, end): (score, s, e)}."""
    win = window_seconds(words) if win is None else win
    targets = torch.tensor([tokens_of(words, song.dictionary, song.star)], dtype=torch.int32)
    found = {} if found is None else found
    n = int(win / song.spf)
    t = -win / 2
    while t < song.duration:
        f0 = max(0, int(t / song.spf))
        r = place(song, words, f0, f0 + n, targets)
        if r:
            score, s, e, _ = r
            key = (round(s, 1), round(e, 1))
            if key not in found or found[key][0] < score:
                found[key] = (score, s, e)
        t += hop
    return found


# ------------------------------------------------------------------ params

# Calibrated on data, not guessed: see calibrate-align-v2 notes in the report
# and `align-v2.py --calibrate`. Units are "z" -- a placement's score above the
# line's own null, in null inter-quartile ranges -- so one set of numbers
# serves a cleanly separated studio vocal and a mono 1964 film track alike.
PARAMS = {
    "blank_penalty": 0.05,   # per-frame cost on CTC blank INSIDE a line: keeps placements compact
    "theta": 0.4,            # z a placement must clear to be worth more than skipping the line
    "gain_cap": 3.0,         # z beyond this adds nothing (one superb line must not buy three bad ones)
    "len_pow": 0.5,          # gain x (line length / median length)^len_pow
    "short": 1.0,            # extra z asked of a line under 12 letters, pro rata
    "skip_open": 1.0,        # opening a run of skipped lines (affine, as in sequence alignment:
                             #   one stray skip is suspicious, a whole unsung verse is one event)
    "skip_line": 0.3,        # each lyric line in the run
    "defer": 0.1,            # a skipped line that HAS ROOM: the gap before the next match holds
                             #   at least `room` x the singing it needs, so it is probably sung
                             #   where the model is deaf (a crowd chorus) and gap-fill will place it
    "room": 0.8,
    "tight_lo": 0.6,         # gap-fill step B: the sub-gap must hold between tight_lo and
    "tight_hi": 3.0,         #   tight_hi x the singing the lines need
    "weak_z": 1.2,           # gap-fill step A: evidence too weak for the DP, enough inside a pinned gap
    "slack": 0.05,           # per second of room BEYOND what the deferred lines need: lines
    "slack_cap": 1.0,        #   floating in a void are less likely than lines filling a gap
    "repeat": 3.0,           # jump back to an earlier line
    "resing": 0.5,           # every line sung AGAIN (at or behind the frontier) must beat theta by this:
                             #   a wrong repeat lights wrong words, a missed one lights none
    "jump": 1.0,             # land inside already-sung text other than at the next line
    "mu": 0.0,               # per second of articulation mass no line claims (bols, unlisted words)
    "stretch": 0.5,          # per expected-duration a placement runs past 2.5x its expected length
    "lrc": 2.0,              # bonus for starting at a same-cut LRC timestamp (fades out over lrc_tol)
    "lrc_tol": 2.0,
    "overlap": 0.3,          # seconds two consecutive placements may overlap
    "min_voiced": 0.4,       # a placement under this voiced fraction is not singing
    "keep": 80,              # placements kept per distinct line
}


# ------------------------------------------------------------------ islands

def islands(mask, gap=0.6, min_len=0.8):
    """[(t0, t1)] sung passages: voiced runs with breaths bridged."""
    m = pick.bridged(mask, gap)
    return [(a * FRAME, b * FRAME) for a, b in pick._runs(m) if (b - a) * FRAME >= min_len]


# ------------------------------------------------------------ all placements

def spot_all(song, texts_words, params, cache_path=None):
    """{text: {"pl": [(score, s, e)], "null": q25, "iqr": spread}} for every
    distinct line. Cached beside the v2 output: spotting is the 5-second part,
    the DP is the part one iterates on."""
    key = {"v": 2, "bp": params["blank_penalty"], "T": song.T, "texts": sorted(texts_words)}
    if cache_path and os.path.exists(cache_path):
        try:
            blob = json.load(open(cache_path, encoding="utf-8"))
            if blob.get("key") == key:
                return blob["spots"]
        except Exception:
            pass
    base = song.emission
    if params["blank_penalty"]:
        song.emission = base.clone()
        song.emission[0, :, 0] -= params["blank_penalty"]
    spots = {}
    try:
        # Pass 1: generous windows. Finds each line wherever it is, however
        # slowly it is sung, and gives the null: how well this text "fits"
        # singing that is not it.
        first = {text: spot(song, words) for text, words in texts_words.items()}
        for text, found in first.items():
            pl = list(found.values())
            vf = [song.voiced(s, e) / max(e - s, 0.05) for _, s, e in pl]
            sc = np.array([p[0] for p, v in zip(pl, vf) if v >= 0.5] or [-5.0])
            spots[text] = {"null": float(np.quantile(sc, 0.25)),
                           "iqr": float(max(0.5, np.quantile(sc, 0.75) - np.quantile(sc, 0.25)))}
        # Pass 2: windows barely longer than the line. A window returns only
        # its single best placement, so an 18s window over a 2.7s hook sung
        # eight times running reports two of the eight (Chaiyya Chaiyya,
        # 0:53-1:12). The singing rate comes from pass 1's surest placements.
        rates = []
        for text, found in first.items():
            chars = sum(len(w) for w in texts_words[text])
            if chars >= 6:
                rates += [(e - s) / chars for score, s, e in found.values()
                          if (score - spots[text]["null"]) / spots[text]["iqr"] >= 2.0]
        spc = statistics.median(rates) if len(rates) >= 5 else 0.15
        for text, words in texts_words.items():
            chars = sum(len(w) for w in words)
            win = max(3.0, 1.6 * spc * chars + 1.0)
            found = first[text]
            if win < 0.8 * window_seconds(words):
                spot(song, words, hop=0.5, win=win, found=found)
            pl = sorted(found.values(), key=lambda x: x[1])
            spots[text]["pl"] = [(round(a_, 3), round(b_, 2), round(c_, 2)) for a_, b_, c_ in pl]
            spots[text]["spc"] = spc
    finally:
        song.emission = base
    # A hook sung forty times contaminates its own null (half its windows are
    # true). No line's null may sit far above the song's typical one.
    typical = statistics.median(v["null"] for v in spots.values()) if spots else -4.0
    for v in spots.values():
        v["null"] = min(v["null"], typical + 0.5)
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"key": key, "spots": spots}, f, ensure_ascii=False)
    return spots


def zscore(spot_entry, score):
    return (score - spot_entry["null"]) / spot_entry["iqr"]


# --------------------------------------------------------------- LRC / cut

def lrc_cut(song, spots_lrc, third_tol=1.0, min_support=0.30, min_third=0.15, good_z=1.5):
    """Is lyrics_synced.lrc the SAME CUT as our audio, judged from where the
    acoustic model hears the LRC's own lines?

    pick-lyrics.py's fit uses the voiced mask alone, which is flat when the stem
    is voiced nearly end to end (Chaiyya Chaiyya has 11 onsets in 7 minutes; Maar
    Daala read as -57s drift and is in fact the same cut). Here every LRC line
    votes for the offsets at which it actually FITS, and the first, middle and
    last third of the lines must elect the same offset.

    Returns {"cut", "offset", "thirds": [...], "support": [...]}."""
    votes = []                                # (line idx, offset, weight)
    for j, (t, text) in enumerate(song.lrc):
        sp = spots_lrc.get(text)
        if not sp:
            continue
        for score, s, e in sp["pl"]:
            z = zscore(sp, score)
            if z >= good_z:
                votes.append((j, s - t, z))
    n = len(song.lrc)
    if n < 8 or len(votes) < 8:
        return {"cut": "unusable", "offset": None, "thirds": [], "support": []}

    def mode(vs):
        if not vs:
            return None
        d = np.array([v[1] for v in vs])
        w = np.array([v[2] for v in vs])
        grid = np.arange(-120, 120.01, 0.25)
        dens = np.array([(w * (np.abs(d - g) <= 0.75)).sum() for g in grid])
        return float(grid[int(dens.argmax())])

    def support(vs, off, idxs):
        hit = {v[0] for v in vs if abs(v[1] - off) <= 1.0}
        return len(hit & set(idxs)) / max(1, len(idxs))

    off = mode(votes)
    thirds, sup = [], []
    for k in range(3):
        idxs = range(k * n // 3, (k + 1) * n // 3)
        vs = [v for v in votes if v[0] in idxs]
        m = mode(vs)
        thirds.append(m)
        sup.append(round(support(vs, m, idxs), 2) if m is not None else 0.0)
    overall = support(votes, off, range(n))
    # Agreement between three independently fitted thirds is the first
    # evidence (by chance they would land anywhere in +-120s); support only
    # has to show the vote was not three flukes -- Maar Daala's last third is
    # an outro of layered voices where few lines fit cleanly, yet it elects
    # the same offset.
    same = (all(m is not None and abs(m - off) <= third_tol for m in thirds)
            and min(sup) >= min_third and overall >= min_support)
    # Second: no STRETCH of the song may confidently elect a different offset.
    # Jiyein Kyun's LRC is the MTV Unplugged take: thirds agree, but eight
    # lines in the middle sit a steady 6s off. A window of six lines dissents
    # when most of it fits somewhere else and little of it fits here. (A hook
    # sung eight times running fits at +-one phrase too, but it ALSO fits here,
    # so it does not dissent.)
    dissent = []
    for a0 in range(0, max(1, n - 5), 3):
        idxs = range(a0, min(n, a0 + 6))
        vs = [v for v in votes if v[0] in idxs]
        m = mode(vs)
        # Only NEARBY dissent counts. A chorus whose lines fit poorly here fits
        # well a whole chorus away (Maar Daala lines 13-18 "elect" -22.75s,
        # the previous refrain); that is repetition, not a different cut, and a
        # real cut shifts everything after it, which the thirds catch.
        if m is None or abs(m - off) <= third_tol or abs(m - off) > 15.0:
            continue
        if support(vs, m, idxs) >= 0.5 and support(vs, off, idxs) < 0.34:
            dissent.append({"lines": [a0 + 1, min(n, a0 + 6)], "at": round(song.lrc[a0][0] + off, 1),
                            "offset": m})
    if dissent:
        same = False
    # refine the offset to the median of the supporting votes
    near = [v[1] for v in votes if abs(v[1] - off) <= 1.0]
    off = float(np.median(near)) if near else off
    return {"cut": "same" if same else "different", "offset": round(off, 2),
            "thirds": thirds, "support": sup, "overall_support": round(overall, 2),
            "dissent": dissent, "rule": 4}


def lrc_map(song, spots_lrc, good_z=1.5, jump=8.0, drift=1.0, step=0.25, span=150.0):
    """A per-line offset for a DIFFERENT-cut LRC: the piecewise mapping.

    Agar Tum Mil Jao's LRC fits at +0.4s until the verse our upload cut, then
    at -77s. Jiyein Kyun's is the Unplugged take: -48s, six seconds looser in
    the middle. Raw timestamps are useless there, but each STRETCH of the LRC
    still carries a human's line spacing. Viterbi over the LRC's lines, state =
    offset: a line scores where the model hears its words, staying put is
    free, creeping costs `drift` per second (a different master speed), and
    jumping anywhere costs `jump` (an edit). Returns [(offset, supported)]
    per LRC line; supported means the line itself votes for its offset."""
    n = len(song.lrc)
    grid = np.arange(-span, span + step / 2, step)
    G = len(grid)
    emit = np.zeros((n, G))
    for j, (t, text) in enumerate(song.lrc):
        sp = spots_lrc.get(text)
        if not sp:
            continue
        for score, s, e in sp["pl"]:
            z = zscore(sp, score)
            if z >= good_z:
                k = int(round((s - t + span) / step))
                lo, hi = max(0, k - 2), min(G, k + 3)
                emit[j, lo:hi] = np.maximum(emit[j, lo:hi], min(z, 3.0))
    reach = int(2.0 / step)                               # creep up to 2s between lines
    score = emit[0].copy()
    back = np.zeros((n, G), dtype=np.int64)
    for j in range(1, n):
        best_prev = int(score.argmax())
        cand = np.full(G, score[best_prev] - jump)
        arg = np.full(G, best_prev)
        for d in range(-reach, reach + 1):
            shifted = np.full(G, -1e18)
            if d >= 0:
                shifted[d:] = score[:G - d]
            else:
                shifted[:d] = score[-d:]
            shifted = shifted - drift * abs(d) * step
            better = shifted > cand
            cand[better] = shifted[better]
            arg[better] = (np.arange(G) - d)[better]
        back[j] = arg
        score = cand + emit[j]
    k = int(score.argmax())
    path = [k]
    for j in range(n - 1, 0, -1):
        k = int(back[j][k])
        path.append(k)
    path.reverse()
    return [(float(grid[k]), bool(emit[j, k] > 0)) for j, k in enumerate(path)]


def trusted_lines(mapping, min_supported=4):
    """Which LRC lines a piecewise map can vouch for: those inside a stretch at
    one offset where at least `min_supported` lines, and at least half of them,
    vote for that offset -- and never past the first or last voting line, nor
    more than two lines from one. The map is extrapolation everywhere else."""
    n = len(mapping)
    trusted = [False] * n
    j = 0
    while j < n:
        k = j
        while k + 1 < n and abs(mapping[k + 1][0] - mapping[j][0]) <= 1.0:
            k += 1
        sup = [x for x in range(j, k + 1) if mapping[x][1]]
        if len(sup) >= min_supported and len(sup) >= 0.5 * (k + 1 - j):
            for x in range(sup[0], sup[-1] + 1):
                if min(abs(x - y) for y in sup) <= 2:
                    trusted[x] = True
        j = k + 1
    return trusted


def lrc_prior_mapped(song, mapping):
    """The prior from a piecewise mapping, from the lines it can vouch for."""
    trusted = trusted_lines(mapping)
    trusted = [ok and 0 <= t + off <= song.duration - 1.0
               for ok, (t, _), (off, _) in zip(trusted, song.lrc, mapping)]
    bodies = {}
    for (t, body), (off, _), ok in zip(song.lrc, mapping, trusted):
        if ok:
            bodies.setdefault(body, []).append(t + off)
    times = {}
    for text in {l["text"] for l in song.lines}:
        ts = []
        for body, tt in bodies.items():
            if same_text(text, body):
                ts += tt
        if ts:
            times[text] = sorted(ts)
    return {"times": times, "all": sorted(t + off for (t, _), (off, _), ok in zip(song.lrc, mapping, trusted) if ok)}


def lrc_prior(song, offset):
    """{"times": {our line text: [LRC times in our clock]}, "all": [...]}. Text
    is matched tolerantly: the LRC may spell, or even script, the line
    differently from lyrics.txt."""
    bodies = {}
    for t, body in song.lrc:
        bodies.setdefault(body, []).append(t + offset)
    times = {}
    for text in {l["text"] for l in song.lines}:
        ts = []
        for body, tt in bodies.items():
            if same_text(text, body):
                ts += tt
        if ts:
            times[text] = sorted(ts)
    return {"times": times, "all": sorted(t + offset for t, _ in song.lrc)}


# ----------------------------------------------------------------- the DP

def sec_per_char(song, spots):
    """The song's own singing rate, from the placements nobody would doubt."""
    for v in spots.values():
        if v.get("spc"):
            return v["spc"]
    rates = []
    for line in song.lines:
        sp = spots[line["text"]]
        chars = sum(len(w) for w in line["words"])
        rates += [(e - s) / chars for score, s, e in sp["pl"] if zscore(sp, score) >= 2.0 and chars >= 6]
    return statistics.median(rates) if len(rates) >= 5 else 0.15


def build_nodes(song, spots, params, prior=None):
    """One node per (text line index, placement). prior = {text_norm: [times]}
    in OUR clock, from a same-cut LRC."""
    nodes = []
    spc = sec_per_char(song, spots)
    song.spc = spc
    # articulation mass a sung character carries in this song, from sure placements
    per = []
    for line in song.lines:
        sp = spots[line["text"]]
        n = sum(len(w) for w in line["words"])
        per += [song.mass(s, e) / n for score, s, e in sp["pl"] if zscore(sp, score) >= 2.0 and n >= 6]
    mpc = statistics.median(per) if len(per) >= 5 else 0.03
    med_chars = statistics.median(sum(len(w) for w in l["words"]) for l in song.lines)
    for j, line in enumerate(song.lines):
        sp = spots[line["text"]]
        chars = sum(len(w) for w in line["words"])
        expect = max(1.0, spc * chars)
        # Evidence scales with how much text was matched. Without this, two
        # three-word fragments out-earn the one six-word line that is really
        # there (Maar Daala 2:51: "(hara rang daala)" + "allah maar daala"
        # beat "allah maang daala allah maang daala", z 2.0+1.3 against 2.4).
        weight = min(2.5, max(0.3, chars / med_chars)) ** params["len_pow"]
        cands = []
        for score, s, e in sp["pl"]:
            if e - s < 0.3:
                continue
            if song.voiced(s, e) / (e - s) < params["min_voiced"]:
                continue
            cands.append((zscore(sp, score), score, s, e))
        cands.sort(reverse=True)
        for z, score, s, e in cands[:params["keep"]]:
            # A six-letter interjection "fits" somewhere in any chorus; its z is
            # an extreme value over hundreds of windows, not evidence. Short
            # lines must clear a higher bar and can never outbid a real line.
            short = max(0.0, (12 - chars) / 12)
            gain = (min(z, params["gain_cap"]) - params["theta"] - params["short"] * short) * weight
            # A two-word line can "fit" across fourteen seconds with its words
            # at either end. It must not be paid for claiming all that singing
            # (the DP credits mu per voiced second a placement covers), and
            # past 2.5x its expected length it is charged for the stretch.
            gain -= params["mu"] * max(0.0, song.mass(s, e) - 1.5 * mpc * chars)
            gain -= params["stretch"] * min(4.0, max(0.0, (e - s) - 2.5 * expect) / expect)
            if prior is not None:
                ts = prior["times"].get(line["text"])
                if ts:
                    d = min(abs(s - t) for t in ts)
                    gain += params["lrc"] * max(0.0, 1.0 - d / params["lrc_tol"])
            nodes.append((j, s, e, gain, score, z, "spot"))
        # Where a same-cut LRC says this line starts and the model found nothing
        # (Chaiyya Chaiyya 1:00-1:08: a chorus the model is deaf to, articulation
        # mass 0.004/s), the timestamp itself becomes a placement. It earns the
        # LRC bonus and nothing else; its words are laid inside the LRC's slot.
        if prior is not None:
            for t in prior["times"].get(line["text"], []):
                if any(abs(c[2] - t) <= 1.0 for c in cands[:params["keep"]]):
                    continue
                nxt = min((x for x in prior["all"] if x > t + 0.5), default=t + 2 * expect)
                e_ = max(t + 0.8, min(nxt - 0.1, t + 2.0 * expect))
                # a timestamp is only a placement if someone is singing there, in OUR
                # audio (Saiyaara's LRC runs 76s past the end of our edit)
                if t < 0 or e_ > song.duration or song.voiced(t, e_) / (e_ - t) < params["min_voiced"]:
                    continue
                nodes.append((j, t, e_, params["lrc"] * 0.75, sp["null"] + params["theta"] * sp["iqr"],
                              params["theta"], "lrc"))
    return nodes


def match(song, nodes, params):
    """The monotonic line-level DP. Returns the chain [(node index, move)] and
    the objective.

    State after a match = (line i just sung, frontier f = furthest line sung so
    far). Moves into line j at a placement starting no earlier than the last
    one ended (less `overlap`):
        next      j == i+1                        free
        skip      j >  f+1                        skip_open + skip_line x (j-1-f) new lines unsung
        return    j == f+1 after a repeat         free
        repeat    j <= i                          repeat
        jump      i+1 < j <= f                    jump
    plus mu x (articulation mass between the two placements) for words no line
    claims. Lines never matched by the end cost skip_line each."""
    L = len(song.lines)
    N = len(nodes)
    if not N:
        return [], 0.0
    P = params
    NEG_ = -1e18
    line = np.array([n[0] for n in nodes])
    s = np.array([n[1] for n in nodes])
    e = np.array([n[2] for n in nodes])
    gain = np.array([n[3] for n in nodes])
    Cs = np.array([song.mass(0, t) for t in s]) * P["mu"]
    Ce = np.array([song.mass(0, t) for t in e]) * P["mu"]
    # Deferred skips need "is there room for the skipped lines in this gap":
    #   voiced(e_m .. s_n) >= room * need(lines f+1 .. j-1)
    # <=> Ve[m] - room*Nd[f] <= Vs[n] - room*Nd[j-1], a threshold on one key, so
    # predecessors are kept in a (frontier x key-bucket) table of running maxima.
    need = np.array([max(1.0, song.spc * sum(len(w) for w in l["words"])) for l in song.lines])
    Nd = np.concatenate([[0.0], np.cumsum(need)])          # Nd[k] = need of lines 0..k-1
    Vs = np.array([song.voiced(0, t) for t in s])
    Ve = np.array([song.voiced(0, t) for t in e])
    BS = 0.5
    kmin = -P["room"] * Nd[-1] - 1.0
    NB = int((Ve.max() - kmin) / BS) + 3
    Bk = np.full((L + 1, NB), NEG_)                          # [frontier+1, key bucket]
    Bkn = np.full((L + 1, NB), -1, dtype=np.int64)
    Bk[0, int((0.0 - P["room"] * Nd[0] - kmin) / BS)] = 0.0   # the start: frontier -1, nothing sung
    fr = np.arange(L + 1)                                   # frontier index fi = f+1; lines sung so far = fi
    order = np.argsort(s, kind="stable")
    by_end = list(np.argsort(e, kind="stable"))
    NEG = -1e18
    B = np.full((L + 1, L + 1), NEG)          # [frontier+1, last line+1] -> best (V + mu*C(end))
    Bn = np.full((L + 1, L + 1), -1, dtype=np.int64)
    B[0, 0] = 0.0
    V = np.full((N, L + 1), NEG)
    back_n = np.full((N, L + 1), -2, dtype=np.int64)     # predecessor node (-1 = start)
    back_f = np.zeros((N, L + 1), dtype=np.int64)
    ar = np.arange(L + 1)
    ptr = 0
    for n in order:
        while ptr < N and e[by_end[ptr]] <= s[n] + P["overlap"]:
            m = by_end[ptr]
            ptr += 1
            if back_n[m].max() == -2 and V[m].max() <= NEG / 2:
                continue
            col = line[m] + 1
            val = V[m] + Ce[m]
            better = val > B[:, col]
            B[better, col] = val[better]
            Bn[better, col] = m
            # the same predecessor, filed by its room key; frontier fi means lines
            # 0..fi-1 are behind us, so the skipped run would start at line fi
            kb = ((Ve[m] - P["room"] * Nd[fr] - kmin) / BS).astype(int) + 1      # +1: round the key UP
            kv = val + P["defer"] * fr
            ok = (val > NEG_ / 2) & (kv > Bk[fr, kb])
            Bk[fr[ok], kb[ok]] = kv[ok]
            Bkn[fr[ok], kb[ok]] = m
        jj = line[n] + 1
        # inside already-sung text: frontier stays
        cost = np.where(ar < jj - 1, P["jump"], np.where(ar == jj - 1, 0.0, P["repeat"]))
        cand = B[jj:, :] - cost[None, :]
        bi = cand.argmax(axis=1)
        bv = cand[np.arange(cand.shape[0]), bi]
        V[n, jj:] = bv + gain[n] - Cs[n] - P["resing"]
        back_n[n, jj:] = Bn[jj:, :][np.arange(cand.shape[0]), bi]
        back_f[n, jj:] = np.arange(jj, L + 1)
        # new text: frontier moves to j, skipping (j-1-f) lines nobody sang
        rows = B[:jj, :]
        ri = rows.argmax(axis=1)
        n_skip = jj - 1 - np.arange(jj)
        rv = rows[np.arange(jj), ri] - P["skip_line"] * n_skip - P["skip_open"] * (n_skip > 0)
        k = int(rv.argmax())
        v_new = rv[k] + gain[n] - Cs[n]
        if v_new > V[n, jj]:
            V[n, jj] = v_new
            back_n[n, jj] = Bn[k, ri[k]]
            back_f[n, jj] = k
        # deferred skip: at least one line skipped (frontier fi <= jj-2) AND room for them
        if jj >= 2:
            b = int((Vs[n] - P["room"] * Nd[jj - 1] - kmin) / BS)
            if b >= 0:
                rect = Bk[:jj - 1, :min(NB, b + 1)]
                ramp = np.minimum(P["slack_cap"], P["slack"] * BS * (rect.shape[1] - 1 - np.arange(rect.shape[1])))
                rect = rect - ramp[None, :]
                flat = int(rect.argmax())
                fi, bb = divmod(flat, rect.shape[1])
                v_def = rect[fi, bb] - P["defer"] * (jj - 1) + gain[n] - Cs[n]
                if rect[fi, bb] > NEG_ / 2 and v_def > V[n, jj]:
                    V[n, jj] = v_def
                    back_n[n, jj] = Bkn[fi, bb]
                    back_f[n, jj] = fi
        V[n, V[n] < NEG / 2] = NEG
    total_voiced = song.mass(0, song.duration) * P["mu"]
    final = V + Ce[:, None] - total_voiced - (P["skip_line"] * (L - ar) + P["skip_open"] * ((L - ar) > 0))[None, :]
    n, f = np.unravel_index(int(final.argmax()), final.shape)
    best = float(final[n, f])
    empty = -total_voiced - P["skip_line"] * L - P["skip_open"]
    if best <= empty:
        return [], empty
    chain = []
    while n >= 0:
        chain.append(int(n))
        n, f = int(back_n[n, f]), int(back_f[n, f])
    chain.reverse()
    return chain, best


# ------------------------------------------------------- words, gaps, report

def refine(song, chain_nodes, params):
    """Word times for each matched line from a local alignment that may not
    cross into its neighbours. Returns segment dicts in time order."""
    base = song.emission
    if params["blank_penalty"]:
        song.emission = base.clone()
        song.emission[0, :, 0] -= params["blank_penalty"]
    segs = []
    try:
        for k, (j, s, e, gain, score, z, src) in enumerate(chain_nodes):
            lo = s - 0.5
            hi = e + 0.5
            if k:
                lo = max(lo, min(segs[-1]["end"], s))
            if k + 1 < len(chain_nodes):
                hi = min(hi, max(chain_nodes[k + 1][1], e))
            words = song.lines[j]["words"]
            r = place(song, words, int(lo / song.spf), int(hi / song.spf) + 1)
            if r is None or abs(r[1] - s) > 1.0:
                r = place(song, words, int((s - 0.1) / song.spf), int((e + 0.1) / song.spf) + 1)
            if r is None:
                n = len(words)
                spans = [(s + (e - s) * i / n, s + (e - s) * (i + 1) / n, score) for i in range(n)]
                r = (score, s, e, spans)
            segs.append(_segment(song.lines[j], j, r, z, src))
    finally:
        song.emission = base
    return segs


def _segment(line, j, r, z, src):
    score, s, e, spans = r
    return {
        "start": round(s, 2), "end": round(max(e, s + 0.2), 2), "text": line["text"],
        "score": round(score, 3),
        "conf": round(float(min(1.0, max(0.0, z / 3.0))), 2),
        "src": src, "line": j,
        "words": [{"word": w, "start": round(a, 2), "end": round(max(b, a + 0.02), 2), "score": round(sc, 3)}
                  for w, (a, b, sc) in zip(line["words"], spans)],
    }


def _forced_block(song, lines_idx, t0, t1):
    """v1's alignment shrunk to one gap: the given lines, in order, stars
    between, inside [t0, t1]. Returns [(line idx, word spans)] or None."""
    units = [song.star]
    for j in lines_idx:
        units += [song.dictionary[c] for w in song.lines[j]["words"] for c in w] + [song.star]
    f0, f1 = int(t0 / song.spf), int(t1 / song.spf)
    if f1 - f0 < 2 * len(units):
        return None
    try:
        aligned, scores = AF.forced_align(song.emission[:, f0:f1], torch.tensor([units], dtype=torch.int32), blank=0)
    except Exception:
        return None
    p, sc = aligned[0].numpy(), scores[0].numpy()
    change = np.flatnonzero(np.diff(p, prepend=-1) != 0)
    run_end = np.append(change[1:], len(p))
    keep = p[change] != 0
    starts, ends = change[keep], run_end[keep]
    if len(starts) != len(units):
        return None
    cs = np.concatenate([[0.0], np.cumsum(sc)])
    means = (cs[ends] - cs[starts]) / (ends - starts)
    k, trial = 1, []
    for j in lines_idx:
        spans = []
        for w in song.lines[j]["words"]:
            n = len(w)
            spans.append(((f0 + starts[k]) * song.spf, (f0 + ends[k + n - 1]) * song.spf, float(means[k:k + n].mean())))
            k += n
        k += 1                                        # the star after the line
        trial.append((j, spans))
    return trial


def _spread_block(song, lines_idx, t0, t1):
    """The lines laid over the gap's voiced time in proportion to length."""
    a_, b_ = int(t0 / FRAME), int(t1 / FRAME)
    vt = np.flatnonzero(pick.bridged(song.mask, 0.6)[a_:b_])
    if len(vt) < 10:
        return None
    total = sum(sum(len(w) for w in song.lines[j]["words"]) for j in lines_idx)
    pos, trial = 0.0, []
    for j in lines_idx:
        spans = []
        for w in song.lines[j]["words"]:
            i0 = int(pos / total * (len(vt) - 1))
            pos += len(w)
            i1 = int(pos / total * (len(vt) - 1))
            spans.append(((a_ + vt[i0]) * FRAME, (a_ + vt[max(i0, i1 - 1)] + 1) * FRAME, -9.0))
        trial.append((j, spans))
    return trial


def _syllables(words):
    return sum(max(1, len(re.findall(r"[aeiou]+", w))) for w in words)


def fill_gaps(song, segs, spots, params):
    """Lines the DP left unmatched that sit, in the text, between two matched
    lines with unclaimed singing between them in the audio. Two steps, both
    confined to the gap, so whatever they get wrong stays there:

      A  weak anchors: a placement inside the gap that the DP found too weak to
         pay for (z under theta) is still evidence once the gap has pinned down
         WHERE the line must be. Best in-order subset, z >= weak_z.
      B  no evidence at all (the model is deaf: a crowd chorus, a slow held
         phrase): lines are laid in a sub-gap only if it holds ABOUT as much
         singing as they need AND the stem has about as many syllable pulses as
         they have syllables -- a held note is voiced for ten seconds and has
         one pulse. Forced alignment first; proportional spread if that crams.
         Otherwise the lines stay skipped and the report says so.
    """
    if not segs:
        return segs, []
    rates = [(sg["end"] - sg["start"]) / max(1, sum(len(w["word"]) for w in sg["words"])) for sg in segs]
    sec_per_char = statistics.median(rates)
    # How long a line takes is best learned from the same line matched elsewhere
    # ("oh ho ho" is eight letters and four seconds); letters x rate otherwise.
    durs = {}
    for sg in segs:
        durs.setdefault(sg["text"], []).append(sg["end"] - sg["start"])
    expected = {t: statistics.median(v) for t, v in durs.items()}

    ref_mass = statistics.median(song.mass(sg["start"], sg["end"]) / max(sg["end"] - sg["start"], 0.1) for sg in segs)

    def want(j):
        by_rate = sum(len(w) for w in song.lines[j]["words"]) * sec_per_char
        # matched copies can be stretched over two sung repetitions; cap them
        return min(expected.get(song.lines[j]["text"], by_rate), 2.0 * max(by_rate, 1.0))

    def judge(trial, t_end, src):
        good = []
        for idx, (j, spans) in enumerate(trial):
            s_, e_ = spans[0][0], spans[-1][1]
            score = float(np.mean([x[2] for x in spans]))
            w_ = want(j)
            # What the room sees is the START. A line found but crushed keeps
            # its start if the next line does not start on top of it.
            nxt = trial[idx + 1][1][0][0] if idx + 1 < len(trial) else t_end
            probe = min(max(e_, s_ + 0.5), s_ + w_)
            z = zscore(spots[song.lines[j]["text"]], score) if score > -9 else 0.0
            # Where the model HEARS words and they score below this line's own
            # null, they are other words: a forced fit there is a lie.
            articulated = song.mass(s_, max(e_, s_ + 0.5)) / max(e_ - s_, 0.5) >= 0.5 * ref_mass
            if src == "fill" and articulated and z < 0:
                continue
            if (song.voiced(s_, probe) / max(probe - s_, 0.05) >= 0.5 and nxt - s_ >= 0.5 * w_
                    and e_ - s_ <= 3.0 * w_ + 2.0):
                if e_ - s_ < 0.5 * w_:
                    k_ = (min(s_ + w_, nxt - 0.05) - s_) / max(e_ - s_, 0.02)
                    spans = [(s_ + (a_ - s_) * k_, s_ + (b_ - s_) * k_, sc_) for a_, b_, sc_ in spans]
                seg = _segment(song.lines[j], j, (score, spans[0][0], spans[-1][1], spans), z, src)
                seg["conf"] = round(min(seg["conf"], 0.3), 2)
                good.append(seg)
        return good

    def blind(lines_idx, t0, t1):
        """Step B for one sub-gap."""
        if not lines_idx or t1 - t0 < 1.0:
            return []
        need = sum(want(j) for j in lines_idx)
        have = song.voiced(t0, t1)
        if not (params["tight_lo"] * need <= have <= params["tight_hi"] * need):
            return []
        syl = sum(_syllables(song.lines[j]["words"]) for j in lines_idx)
        if song.pulses(t0, t1) < 0.5 * syl:
            return []
        good = []
        trial = _forced_block(song, lines_idx, t0, t1)
        if trial:
            good = judge(trial, t1, "fill")
        if len(good) < 0.6 * len(lines_idx):
            trial = _spread_block(song, lines_idx, t0, t1)
            good = judge(trial, t1, "spread") if trial else []
        return good if len(good) >= 0.6 * len(lines_idx) else []

    def weak_anchors(lines_idx, t0, t1):
        """Step A: best in-order subset of placements inside the gap."""
        cands = []
        for k, j in enumerate(lines_idx):
            sp = spots[song.lines[j]["text"]]
            w_ = want(j)
            for score, s_, e_ in sp["pl"]:
                if s_ < t0 - 0.2 or e_ > t1 + 0.2 or e_ - s_ < 0.3 or e_ - s_ > 3.0 * w_ + 2.0:
                    continue
                z = zscore(sp, score)
                if z >= params["weak_z"] and song.voiced(s_, e_) / (e_ - s_) >= params["min_voiced"]:
                    cands.append((s_, e_, k, j, z, score))
        cands.sort()
        best, prev = [], []
        for c, (s_, e_, k, j, z, score) in enumerate(cands):
            b_, p_ = z, -1
            for c2 in range(c):
                s2, e2, k2 = cands[c2][0], cands[c2][1], cands[c2][2]
                if k2 < k and e2 <= s_ + params["overlap"] and best[c2] + z > b_:
                    b_, p_ = best[c2] + z, c2
            best.append(b_)
            prev.append(p_)
        if not cands:
            return []
        c = int(np.argmax(best))
        chain = []
        while c >= 0:
            chain.append(cands[c])
            c = prev[c]
        return chain[::-1]

    # Step 0 -- identical neighbours are interchangeable. "Tu jaane na, tu jaane
    # na" is written twice running; the DP lit the first sung copy as line 26 and
    # deferred line 25 into the gap BEFORE it, when the unplaced copy was plainly
    # sung just AFTER. For a run of identical lines, look for the missing copies
    # anywhere from the line before the run to the line after it, then renumber
    # the copies in time order.
    segs = sorted(segs, key=lambda x: x["start"])
    step0 = []
    j0 = 0
    while j0 < len(song.lines):
        j1 = j0
        while j1 + 1 < len(song.lines) and song.lines[j1 + 1]["text"] == song.lines[j0]["text"]:
            j1 += 1
        if j1 > j0:
            idx = [k for k, sg in enumerate(segs) if j0 <= sg["line"] <= j1]
            have_lines = {segs[k]["line"] for k in idx}
            n_missing = (j1 - j0 + 1) - len(have_lines)
            if idx and n_missing > 0 and idx == list(range(idx[0], idx[-1] + 1)) and len(have_lines) == len(idx):
                T0 = segs[idx[0] - 1]["end"] if idx[0] > 0 else 0.0
                T1 = segs[idx[-1] + 1]["start"] if idx[-1] + 1 < len(segs) else song.duration
                taken = [(segs[k]["start"], segs[k]["end"]) for k in idx]
                sp = spots[song.lines[j0]["text"]]
                w_ = want(j0)
                cands = sorted(((zscore(sp, sc), s_, e_, sc) for sc, s_, e_ in sp["pl"]
                                if s_ >= T0 - 0.2 and e_ <= T1 + 0.2 and 0.3 <= e_ - s_ <= 3.0 * w_ + 2.0), reverse=True)
                new = []
                for z, s_, e_, sc in cands:
                    if len(new) >= n_missing or z < params["weak_z"]:
                        break
                    if song.voiced(s_, e_) / (e_ - s_) < params["min_voiced"]:
                        continue
                    if any(min(e_, b_) - max(s_, a_) > params["overlap"] for a_, b_ in taken):
                        continue
                    taken.append((s_, e_))
                    words = song.lines[j0]["words"]
                    r = place(song, words, int((s_ - 0.1) / song.spf), int((e_ + 0.1) / song.spf) + 1)
                    if r is None:
                        n_ = len(words)
                        r = (sc, s_, e_, [(s_ + (e_ - s_) * i / n_, s_ + (e_ - s_) * (i + 1) / n_, sc) for i in range(n_)])
                    new.append(_segment(song.lines[j0], j0, r, z, "weak"))
                # Renumber the copies in time order from the run's first index,
                # whether or not a missing copy was found: the copies still
                # missing then fall in the gap AFTER the run, where a hook
                # chorus continues, not before it, where the verse ended.
                copies = sorted([segs[k] for k in idx] + new, key=lambda x: x["start"])
                for n_, sg in enumerate(copies):
                    sg["line"] = j0 + n_
                segs = sorted(segs[:idx[0]] + copies + segs[idx[-1] + 1:], key=lambda x: x["start"])
                step0 += [sg["line"] for sg in new]
        j0 = j1 + 1

    out, filled, seen = [], list(step0), set()
    bounds = [(None, segs[0])] + list(zip(segs, segs[1:])) + [(segs[-1], None)]
    frontier = -1
    for a, b in bounds:
        if a is not None:
            out.append(a)
            frontier = max(frontier, a["line"])
        if b is not None and b["line"] <= frontier:
            continue                                  # a repeat: nothing new was skipped
        hi_line = b["line"] if b is not None else len(song.lines)
        missing = [j for j in range(frontier + 1, hi_line) if j not in seen]
        if not missing:
            continue
        t0 = a["end"] if a is not None else 0.0
        t1 = b["start"] if b is not None else song.duration
        anchors = weak_anchors(missing, t0, t1)
        # A block the gap cannot hold is a cut verse (Agar Tum Mil Jao: eleven
        # lines needing 30s against an interlude with 20s of humming): weak
        # anchors may still claim a line on evidence, but nothing is laid blind.
        block_fits = song.voiced(t0, t1) >= params["tight_lo"] * sum(want(j) for j in missing)
        new = []
        cuts = [(t0, -1)] + [(e_, k) for s_, e_, k, j, z, score in anchors]
        for (s_, e_, k, j, z, score) in anchors:
            words = song.lines[j]["words"]
            r = place(song, words, int((s_ - 0.1) / song.spf), int((e_ + 0.1) / song.spf) + 1)
            if r is None:
                n = len(words)
                r = (score, s_, e_, [(s_ + (e_ - s_) * i / n, s_ + (e_ - s_) * (i + 1) / n, score) for i in range(n)])
            seg = _segment(song.lines[j], j, r, z, "weak")
            new.append(seg)
        starts = [x[0] for x in anchors] + [t1]
        for (g0, k0), g1, k1 in zip(cuts, starts, [x[2] for x in anchors] + [len(missing)]):
            if block_fits:
                new += blind(missing[k0 + 1:k1], g0, g1)
        for seg in new:
            out.append(seg)
            seen.add(seg["line"])
            filled.append(seg["line"])
    out.sort(key=lambda x: x["start"])
    return out, filled


def unmatched_islands(song, segs, spots, min_sec=4.0):
    """Voiced passages over `min_sec` that no line claims, each with the cheap
    evidence for 'wordless' against 'words are missing from the lyrics'."""
    cover = np.zeros(len(song.mask), dtype=bool)
    for sg in segs:
        cover[max(0, int((sg["start"] - 0.3) / FRAME)):int((sg["end"] + 0.3) / FRAME)] = True
    inside = [song.nonblank[int(sg["start"] / song.spf):int(sg["end"] / song.spf)].mean()
              for sg in segs if sg["end"] - sg["start"] > 0.5]
    ref = statistics.median(inside) if inside else 0.3
    matched_lines = {sg["line"] for sg in segs}
    out = []
    for t0, t1 in islands(song.mask):
        a, b = int(t0 / FRAME), int(t1 / FRAME)
        free = ~cover[a:b] & pick.bridged(song.mask, 0.6)[a:b]
        for r0, r1 in pick._runs(free):
            u0, u1 = (a + r0) * FRAME, (a + r1) * FRAME
            if u1 - u0 < min_sec:
                continue
            best = (None, -9.0, None)
            for text, sp in spots.items():
                for score, s, e in sp["pl"]:
                    if s >= u0 - 0.5 and e <= u1 + 0.5:
                        z = zscore(sp, score)
                        if z > best[1]:
                            best = (text, z, s)
            artic = float(song.nonblank[int(u0 / song.spf):int(u1 / song.spf)].mean()) / max(ref, 1e-6)
            before = [sg for sg in segs if sg["end"] <= u0 + 0.5]
            after = [sg for sg in segs if sg["start"] >= u1 - 0.5]
            lo = before[-1]["line"] if before else -1
            hi = after[0]["line"] if after else len(song.lines)
            between = [j + 1 for j in range(lo + 1, hi) if j not in matched_lines]
            if between and artic >= 0.35:
                verdict = (f"sung; lyric lines {between[0]}-{between[-1]} were skipped around here and may "
                           f"belong here (the model could not place them)")
            elif best[1] >= 2.5:
                verdict = "a known line fits here: possible echo or uncounted repeat"
            elif artic >= 0.6:
                verdict = "sung and articulated, no line fits: words may be missing from the lyrics"
            else:
                verdict = ("sung, no words the model can hear (alaap, bols, humming, a held note, "
                           "or a chorus too blurred to articulate)")
            out.append({"start": round(u0, 1), "end": round(u1, 1), "seconds": round(u1 - u0, 1),
                        "articulation": round(artic, 2), "skipped_lines_between": between, "best_line": best[0],
                        "best_line_z": round(best[1], 2), "verdict": verdict})
    return out


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


# -------------------------------------------------------------------- song

def align_loaded(song, spots, params, prior=None):
    """Nodes -> DP -> word times -> gap fill, on a song already in memory.
    (The calibration loop calls this hundreds of times per song.)"""
    nodes = build_nodes(song, spots, params, prior)
    chain, objective = match(song, nodes, params)
    segs = refine(song, [nodes[n] for n in chain], params)
    segs, filled = fill_gaps(song, segs, spots, params)
    for sg in segs:
        if sg["end"] <= sg["start"]:
            sg["end"] = round(sg["start"] + 0.5, 2)
    return segs, filled, objective


def align_song(song_dir, out_root=DEFAULT_OUT, use_lrc=True, params=None, write=True, quiet=False):
    params = dict(PARAMS, **(params or {}))
    name = os.path.basename(os.path.abspath(song_dir).rstrip("/"))
    if name in HANDS_OFF:
        print(f"  SKIP {name} (hand-built; left alone)")
        return None
    t_all = time.time()
    song = Song(song_dir)
    out_dir = os.path.join(out_root, name)
    t0 = time.time()
    texts = {}
    for l in song.lines:
        texts.setdefault(l["text"], l["words"])
    cache_root = os.path.join(DEFAULT_OUT, "_spots")
    spots = spot_all(song, texts, params, os.path.join(cache_root, name + ".json"))
    t_spot = time.time() - t0

    cut, prior = None, None
    if song.lrc:
        lt = {}
        for _, body in song.lrc:
            w = al.normalize_words(body, song.dictionary)
            if w:
                lt.setdefault(body, w)
        spots_lrc = spot_all(song, lt, params, os.path.join(cache_root, name + ".lrc.json"))
        cut = lrc_cut(song, spots_lrc)
        if use_lrc and cut["cut"] == "same":
            prior = lrc_prior(song, cut["offset"])
        elif use_lrc and cut["cut"] == "different":
            mapping = lrc_map(song, spots_lrc)
            prior = lrc_prior_mapped(song, mapping)
            segs_, j0 = [], 0
            for j in range(1, len(mapping) + 1):
                if j == len(mapping) or abs(mapping[j][0] - mapping[j0][0]) > 1.0:
                    segs_.append({"lrc_lines": [j0 + 1, j], "offset": mapping[j0][0],
                                  "supported": sum(1 for x in mapping[j0:j] if x[1])})
                    j0 = j
            cut["piecewise"] = segs_
            if not prior["times"]:
                prior = None

    t0 = time.time()
    segs, filled, objective = align_loaded(song, spots, params, prior)
    t_dp = time.time() - t0

    matched = {sg["line"] for sg in segs}
    skipped = [{"line": j + 1, "text": l["text"]} for j, l in enumerate(song.lines) if j not in matched]
    repeats, seen = [], set()
    for sg in segs:
        if sg["line"] in seen:
            repeats.append({"line": sg["line"] + 1, "text": sg["text"], "at": sg["start"], "at_mmss": mmss(sg["start"])})
        seen.add(sg["line"])
    isl = unmatched_islands(song, segs, spots)
    elapsed = time.time() - t_all
    report = {
        "song": name, "duration": round(song.duration, 1), "lyrics_lines": len(song.lines),
        "output_lines": len(segs), "objective": round(objective, 2),
        "lrc": cut, "lrc_prior_used": prior is not None,
        "skipped_lines": skipped, "repeated_lines": repeats, "gap_filled_lines": [j + 1 for j in filled],
        "unmatched_islands": isl,
        "first_line_at": segs[0]["start"] if segs else None,
        "seconds": {"total": round(elapsed, 1), "spotting": round(t_spot, 1), "dp": round(t_dp, 2),
                    "emission_cached": getattr(song, "cached", None)},
        "params": params,
    }
    if write:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "lyrics_timed.json"), "w", encoding="utf-8") as f:
            json.dump(segs, f, indent=2, ensure_ascii=False, default=float)
        # roman.json is keyed by line text, so the reviewed spellings lay straight
        # back over a fresh alignment. The job is READ from the library; the
        # script writes only into out_dir.
        job = os.path.join(song.dir, "roman.json")
        if os.path.exists(job):
            r = subprocess.run([sys.executable, os.path.join(HERE, "romanize-lyrics.py"), "apply", out_dir, job],
                               capture_output=True, text=True)
            msg = (r.stdout or r.stderr).strip()
            report["roman"] = msg.splitlines()[-1] if msg else ""
            bak = os.path.join(out_dir, "lyrics_timed.json.preroman.bak")
            if os.path.exists(bak):
                os.remove(bak)                        # a backup of our own scratch output is noise
        with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, ensure_ascii=False, default=float)
    if not quiet:
        print(f"  {name}: {len(song.lines)} lyric lines -> {len(segs)} timed ({len(skipped)} skipped, "
              f"{len(repeats)} repeats, {len(filled)} gap-filled), first line {mmss(segs[0]['start']) if segs else '-'}, "
              f"{len(isl)} unclaimed islands >4s; lrc {cut['cut'] if cut else 'none'}"
              f"{' (prior used)' if prior is not None else ''}; {elapsed:.1f}s (spot {t_spot:.1f}s, dp {t_dp:.2f}s)")
    return segs, report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("song_dirs", nargs="+")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--no-lrc", action="store_true", help="ignore lyrics_synced.lrc (the honest benchmark mode)")
    ap.add_argument("--emit-only", action="store_true", help="only warm the emission cache")
    args = ap.parse_args()
    lib = os.path.realpath(os.path.expanduser("~/Music/karaoke/htdemucs"))
    if os.path.realpath(args.out).startswith(lib):
        sys.exit("refusing to write v2 output inside the library")
    for d in args.song_dirs:
        if args.emit_only:
            s = Song(d)
            print(f"  {s.name}: emission {'cached' if s.cached else 'computed'}")
            continue
        align_song(d, args.out, use_lrc=not args.no_lrc)


if __name__ == "__main__":
    main()
