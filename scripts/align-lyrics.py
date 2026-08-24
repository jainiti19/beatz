#!/usr/bin/env python3
"""
Force-align Genius lyrics to the separated vocals track using torchaudio's MMS_FA.

Unlike generate-timed-lyrics.py, this never *transcribes*. It takes the lyrics we
already know are correct and finds where in the audio each word is actually sung.
Alignment is non-autoregressive (frame scoring + Viterbi), so it cannot drift,
hallucinate, or reorder — the text is fixed, only the timing is solved for.

Whisper is not involved. That matters because Whisper's `base` model transcribes
sung Hindi into garbage ("Shar kardesim" for Hudd Hudd Dabangg), which is both
unusable as display text and useless to match Genius lines against.

Output: lyrics_timed.json — line-level spans with nested word-level spans.

Usage: align-lyrics.py <stems_dir> [--force]
       align-lyrics.py --batch <htdemucs_dir> [--force]
       align-lyrics.py --batch <htdemucs_dir> --repair   (post-passes only, no model)
"""

import sys
import os
import re
import json
import unicodedata

import torch
import torchaudio
import torchaudio.functional as AF
from torchaudio.pipelines import MMS_FA as bundle

SAMPLE_RATE = bundle.sample_rate          # 16000
CHUNK_SECONDS = 30                        # attention is O(n^2); a whole song will not fit
OVERLAP_SECONDS = 2                       # context either side of a chunk, then discarded

_model = None
_dictionary = None
_uroman = None


def get_model(int8=False):
    """Load MMS_FA once. with_star=True lets audio with no matching text be absorbed.

    int8 dynamic quantization of the Linear layers roughly doubles CPU throughput.
    The transformer weights are what dominate here, so this is the single biggest
    lever available without a GPU — see the header note on why vectorizing the
    Python side would achieve nothing.
    """
    global _model, _dictionary
    if _model is None:
        model = bundle.get_model(with_star=True)
        model.eval()
        if int8:
            model = torch.ao.quantization.quantize_dynamic(
                model, {torch.nn.Linear}, dtype=torch.qint8
            )
        _model = model
        _dictionary = bundle.get_dict(star="*")
    return _model, _dictionary


def romanize(text):
    """Devanagari -> Latin. Genius lyrics are usually already romanized; a few aren't."""
    global _uroman
    if all(ord(c) < 128 for c in text):
        return text
    if _uroman is None:
        import uroman as ur
        _uroman = ur.Uroman()
    return _uroman.romanize_string(text)


def normalize_words(line, dictionary):
    """Reduce a lyric line to tokens MMS_FA can represent, dropping anything it can't.

    Index 0 is the CTC blank (spelled '-' in this dictionary) and must never appear
    in a target, so hyphens split words instead: "khud-garzi" -> "khud", "garzi".
    """
    allowed = {c for c, i in dictionary.items() if i != 0 and c != "*"}
    line = romanize(line)
    line = unicodedata.normalize("NFKD", line)
    line = "".join(c for c in line if not unicodedata.combining(c))
    line = line.lower().replace("’", "'")
    line = re.sub(r"[-‐-―_/]", " ", line)
    words = []
    for raw in line.split():
        word = "".join(c for c in raw if c in allowed)
        if word:
            words.append(word)
    return words


def load_vocals(path):
    """Load a stem as 16 kHz mono."""
    waveform, sr = torchaudio.load(path)
    if waveform.size(0) > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sr != SAMPLE_RATE:
        waveform = torchaudio.functional.resample(waveform, sr, SAMPLE_RATE)
    return waveform


def compute_emission(model, waveform):
    """Run the acoustic model in overlapping chunks and stitch the frame posteriors.

    Each chunk is scored with `OVERLAP_SECONDS` of extra context on both sides, but
    only the frames belonging to the chunk's own span are kept — so the result is
    identical in shape to a single pass, without the quadratic attention cost.
    """
    total = waveform.size(1)
    step = CHUNK_SECONDS * SAMPLE_RATE
    pad = OVERLAP_SECONDS * SAMPLE_RATE

    # Determine the model's frame stride empirically, from the *difference* between
    # two short probes. A single probe's samples/frames ratio is biased by the conv
    # receptive field at the edges (a 2s probe reports 323 against a true 320), and
    # a 1% stride error compounds across chunks into seconds of drift. Differencing
    # cancels the edge term exactly, and two 2-3s probes cost far less than the
    # full-chunk probe that would otherwise be needed to wash the bias out.
    a_len, b_len = 2 * SAMPLE_RATE, 3 * SAMPLE_RATE
    if total < b_len:
        stride = 320                                   # too short to probe; wav2vec2 default
    else:
        with torch.inference_mode():
            a, _ = model(waveform[:, :a_len])
            b, _ = model(waveform[:, :b_len])
        stride = round((b_len - a_len) / (b.size(1) - a.size(1)))

    parts = []
    for start in range(0, total, step):
        end = min(start + step, total)
        lo, hi = max(0, start - pad), min(total, end + pad)
        with torch.inference_mode():
            emission, _ = model(waveform[:, lo:hi])
        # Drop the frames contributed by the context padding on each side.
        drop_lo = (start - lo) // stride
        keep = max(1, round((end - start) / stride))
        parts.append(emission[:, drop_lo:drop_lo + keep])

    return torch.cat(parts, dim=1)


def align(emission, units, dictionary):
    """Viterbi-align token units against frame posteriors.

    `units` is a list of (kind, tokens). Star units absorb audio with no lyrics —
    instrumental breaks, ad-libs, Genius omissions — so the surrounding real words
    are not stretched across them.
    """
    targets = [t for _, tokens in units for t in tokens]
    targets = torch.tensor([targets], dtype=torch.int32)

    aligned, scores = AF.forced_align(emission, targets, blank=0)
    spans = AF.merge_tokens(aligned[0], scores[0])

    out, i = [], 0
    for kind, tokens in units:
        chunk = spans[i:i + len(tokens)]
        i += len(tokens)
        if kind == "word" and chunk:
            out.append(chunk)
        elif kind == "word":
            out.append(None)          # token was consumed entirely by blanks
    return out


def _regroup(word_spans, line_list, seconds_per_frame):
    """Turn flat per-word token spans back into line segments with times."""
    segments, cursor = [], 0
    for line in line_list:
        spans = word_spans[cursor:cursor + len(line["words"])]
        cursor += len(line["words"])
        present = [(w, sp) for w, sp in zip(line["words"], spans) if sp]
        if not present:
            continue
        words_out = [
            {
                "word": w,
                "start": round(sp[0].start * seconds_per_frame, 2),
                "end": round(sp[-1].end * seconds_per_frame, 2),
                # Mean per-token Viterbi confidence. Low values mean the model did
                # not really find this text in the audio — the strongest signal we
                # have that the lyrics say something the singer didn't.
                "score": round(sum(t.score for t in sp) / len(sp), 3),
            }
            for w, sp in present
        ]
        segments.append({
            "start": words_out[0]["start"],
            "end": words_out[-1]["end"],
            "text": line["text"],
            "score": round(sum(w["score"] for w in words_out) / len(words_out), 3),
            "words": words_out,
        })
    return segments


def voiced_mask(waveform, frame=0.02, floor_db=35):
    """Boolean per-20ms-frame 'someone is singing here' mask for the vocals stem."""
    hop = int(frame * SAMPLE_RATE)
    power = (waveform[0] ** 2).unsqueeze(0).unsqueeze(0)
    rms = torch.sqrt(torch.nn.functional.avg_pool1d(power, hop, hop)).squeeze()
    db = 20 * torch.log10(rms + 1e-10)
    return (db > db.max() - floor_db).numpy()


def estimate_period_for_span(waveform, t0, t1, min_period=1.2, max_period=12.0):
    """Find the repeated phrase length, in seconds, from mel self-similarity.

    A chorus repeats at the song's musical rate, so one period serves the whole
    song. Estimating it per block is unreliable: blocks containing long
    instrumental stretches are near-stationary and correlate strongly at *every*
    lag, which yields nonsense (a 1.0s period implying 40 repetitions).

    Autocorrelation also peaks on harmonics — Chaiyya Chaiyya peaks at 5.34s
    (two-phrase group) above 2.67s (the phrase itself). We want the fundamental,
    so among peaks within 60% of the best we take the shortest.
    """
    import torchaudio.transforms as T
    mel = T.MelSpectrogram(SAMPLE_RATE, n_fft=2048, hop_length=512, n_mels=48)
    fps = SAMPLE_RATE / 512

    if t1 - t0 < 2 * min_period:
        return None
    if True:
        seg = torch.log(mel(waveform[0][int(t0 * SAMPLE_RATE):int(t1 * SAMPLE_RATE)]) + 1e-8)
        seg = (seg - seg.mean(1, keepdim=True)) / (seg.std(1, keepdim=True) + 1e-8)
        seg = seg.numpy()
        n = seg.shape[1]
        curve = []
        for lag in range(int(min_period * fps), min(int(max_period * fps), n - 10)):
            a, b = seg[:, :n - lag], seg[:, lag:]
            curve.append((lag / fps, float((a * b).mean())))
        if len(curve) < 3:
            return None
        peaks = [(pp, r) for i, (pp, r) in enumerate(curve)
                 if 0 < i < len(curve) - 1 and r > curve[i - 1][1] and r > curve[i + 1][1]]
        if not peaks:
            return None
        best = max(r for _, r in peaks)
        if best < 0.20:
            return None                    # no real periodicity here
        top = max(peaks, key=lambda x: x[1])[0]
        # Autocorrelation peaks on harmonics: Chaiyya Chaiyya's strongest peak is
        # 5.34s, but that is two phrases — the phrase itself is 2.66s, which the
        # human-synced LRC corroborates (its chorus lines sit 2.5-3.9s apart).
        # Rather than loosen the peak threshold globally, test the subharmonics
        # explicitly: if half (or a third of) the top period is itself a peak with
        # real support, that is the fundamental.
        def peak_near(target, tol=0.15):
            near = [(pp, r) for pp, r in peaks if abs(pp - target) <= tol * target]
            return max(near, key=lambda x: x[1]) if near else None

        for divisor in (2, 3):
            sub = peak_near(top / divisor)
            if sub and sub[1] >= 0.35 * best and top / divisor >= min_period:
                top = sub[0]
                break
        return top


def correct_repeat_counts(waveform, lines, segments, seconds_per_frame):
    """Rewrite the line list so repeated runs use the count the audio supports.

    Lyrics sources disagree and both under-count here: Genius lists 31 "Chal
    chaiyya" lines and LRCLIB 23, while the audio sings roughly 43. A text line
    stretched over two sung repetitions makes the highlight move at half the
    singer's rate, which reads as drift.

    Count = voiced seconds in the block / phrase period. Voiced seconds rather
    than wall-clock, so instrumental gaps inside a block do not inflate the
    count. Once the count is right the alignment itself places the repetitions —
    that is what forced alignment is good at, given the correct text.

    Returns the new line list, or None when nothing changed.
    """
    if len(segments) != len(lines):
        return None                        # a line dropped out; indices unreliable

    runs, start = [], 0
    for i in range(1, len(segments) + 1):
        if i == len(segments) or segments[i]["text"].strip().lower() != \
                segments[start]["text"].strip().lower():
            runs.append((start, i))
            start = i

    repeated = [(lo, hi) for lo, hi in runs if hi - lo >= 2]
    if not repeated:
        return None

    voiced = voiced_mask(waveform)

    def voiced_seconds(t0, t1):
        return voiced[int(t0 / 0.02):int(t1 / 0.02)].sum() * 0.02

    spans = [(segments[lo]["start"], segments[hi - 1]["end"]) for lo, hi in repeated]

    # Each repeated line has its own natural length — a nine-word verse line does
    # not take the same time as the four-word chorus hook, so one song-wide period
    # would multiply long lines wrongly. Estimate per run, and fall back to the
    # median of the confident runs when a run is too gappy to measure (largely
    # instrumental spans are near-stationary and correlate at every lag).
    raw = []
    for t0, t1 in spans:
        vf = (voiced_seconds(t0, t1) / (t1 - t0)) if t1 > t0 else 0.0
        raw.append(estimate_period_for_span(waveform, t0, t1) if vf >= 0.85 else None)

    confident = sorted(x for x in raw if x)
    if not confident:
        return None
    fallback = confident[len(confident) // 2]

    # A given line takes the same time every time it is sung, so pool the estimates
    # for each distinct text and use their median. Per-run estimates are too noisy
    # on their own — the same "Chal chaiyya" hook measured 2.66s in some blocks and
    # its 5.34s harmonic in others, which would then multiply those blocks wrongly.
    by_text = {}
    for (lo, hi), est in zip(repeated, raw):
        if est:
            by_text.setdefault(segments[lo]["text"].strip().lower(), []).append(est)
    pooled = {t: sorted(v)[len(v) // 2] for t, v in by_text.items()}

    periods = [
        pooled.get(segments[lo]["text"].strip().lower()) or est or fallback
        for (lo, hi), est in zip(repeated, raw)
    ]

    out, changed = [], False
    ri = 0
    for lo, hi in runs:
        n = hi - lo
        line = lines[lo]
        if n < 2:
            out.append(line)
            continue

        t0, t1 = spans[ri]
        period = periods[ri] or fallback
        ri += 1
        v = voiced_seconds(t0, t1)
        k = max(1, round(v / period))
        # Refuse wild rewrites — a 10x jump means the period or the span is wrong.
        if k > 4 * n or k < n / 4:
            k = n
        if k != n:
            changed = True
            print(f"    repeat count {n} -> {k}  ({t0:.1f}-{t1:.1f}s, {v:.1f}s voiced, "
                  f"period {period:.2f}s) {line['text'][:34]!r}")
        out.extend([line] * k)

    return out if changed else None


def redistribute_repeats(segments):
    """Give repeated lines a consistent internal rhythm, without moving them.

    Two distinct problems live here, and only one should be fixed by rewriting.

    Line *placement* is the aligner's job, and once the repetition count is right
    it does it well. An earlier version also spread each run's lines evenly across
    its wall-clock span; that dropped lines into instrumental gaps (one run is only
    44% voiced) and pushed word-on-voiced-audio down from 84% to 72% — no better
    than chance. So spans are left exactly as aligned.

    Word rhythm *within* a line is still worth normalising. Where the aligner has
    any slack it dumps it into a single word — one "chaiyya" held 2.97s while its
    neighbours got 0.16s — which makes the sweep stall then lurch. Identical text
    sung repeatedly has near-identical internal rhythm, so take the median relative
    duration at each word position across the run and lay every repetition out with
    it. Medians ignore the outliers where the slack landed.
    """
    if not segments:
        return segments

    runs, start = [], 0
    for i in range(1, len(segments) + 1):
        if i == len(segments) or segments[i]["text"].strip().lower() != \
                segments[start]["text"].strip().lower():
            runs.append((start, i))
            start = i

    fixed = 0
    for lo, hi in runs:
        n = hi - lo
        if n < 2:
            continue
        counts = {len(segments[i]["words"]) for i in range(lo, hi)}
        if len(counts) != 1 or counts.pop() == 0:
            continue                      # mixed word counts; no shared profile

        # Only lines where the aligner dumped slack into one word need rescuing.
        # Most do not: the median line has its longest word at 1.8x the line
        # median, and rewriting those was overriding real per-instance rhythm —
        # the sweep then drifted inside a line and snapped back at its boundary.
        def lopsided(seg):
            ws = [w["end"] - w["start"] for w in seg["words"]]
            if len(ws) < 2:
                return False
            mid = sorted(ws)[len(ws) // 2]
            return mid > 0 and max(ws) / mid > 3.0

        healthy, broken = [], []
        for i in range(lo, hi):
            (broken if lopsided(segments[i]) else healthy).append(i)
        if not broken:
            continue

        # Build the shared rhythm from the well-aligned repetitions only.
        relatives = []
        for i in (healthy or list(range(lo, hi))):
            ws = segments[i]["words"]
            total = ws[-1]["end"] - ws[0]["start"]
            if total > 0:
                relatives.append([(w["end"] - w["start"]) / total for w in ws])
        if not relatives:
            continue
        med = [
            sorted(r[k] for r in relatives)[len(relatives) // 2]
            for k in range(len(relatives[0]))
        ]
        if sum(med) <= 0:
            continue
        profile = [x / sum(med) for x in med]

        for i in broken:
            seg = segments[i]
            span = seg["end"] - seg["start"]
            if span <= 0:
                continue
            t = seg["start"]
            for w, frac in zip(seg["words"], profile):
                w["start"] = round(t, 2)
                t += frac * span
                w["end"] = round(t, 2)
            fixed += 1

    if fixed:
        print(f"    smoothed word rhythm on {fixed} lopsided lines")
    return segments


def reanchor_outliers(segments, max_gap=6.0, min_span=12.0):
    """Pull a word Viterbi flung across an instrumental break back onto its line.

    A line whose words are all sung together can still come back spanning fifty
    seconds if one word matched something in an intro or outro: 'aisa' landing at
    3s while the rest of 'Aisa dekha nahi khoobsurat koi' is sung at 51s. Nothing
    is wrong with the words in between — the line span is simply the distance
    between a false match and the real one, and the UI keeps the line lit for the
    whole break because it highlights on start..end.

    Only leading and trailing runs move, and only across a gap far wider than any
    breath, so a genuinely held note is left alone. Words always move *inward*
    toward the rest of their line, which cannot break monotonicity against the
    neighbouring lines: Viterbi already placed the previous line before this
    line's first word and the next line after its last.
    """
    for seg in segments:
        words = seg.get("words") or []
        if len(words) < 2:
            continue

        for _ in range(4):          # a line can carry an outlier at both ends
            span = seg["end"] - seg["start"]
            if span < min_span:
                break
            gaps = [(w2["start"] - w1["end"], i)
                    for i, (w1, w2) in enumerate(zip(words, words[1:]))]
            gap, idx = max(gaps)
            if gap <= max_gap:
                break

            head, tail = words[:idx + 1], words[idx + 1:]
            # The shorter side is the stray one; a tie means trust the later
            # cluster, since false matches cluster in intros.
            if len(head) <= len(tail):
                anchor = tail[0]["start"]
                for w in reversed(head):
                    dur = round(w["end"] - w["start"], 2)
                    w["end"] = round(anchor, 2)
                    w["start"] = round(anchor - dur, 2)
                    anchor -= dur
            else:
                anchor = head[-1]["end"]
                for w in tail:
                    dur = round(w["end"] - w["start"], 2)
                    w["start"] = round(anchor, 2)
                    w["end"] = round(anchor + dur, 2)
                    anchor += dur

            seg["start"] = words[0]["start"]
            seg["end"] = words[-1]["end"]
    return segments


def process_song(stems_dir, force=False, int8=False):
    name = os.path.basename(stems_dir.rstrip("/"))
    out_path = os.path.join(stems_dir, "lyrics_timed.json")

    if os.path.exists(out_path) and not force:
        print(f"  SKIP {name} (already aligned; use --force)")
        return "skip"

    lyrics_path = os.path.join(stems_dir, "lyrics.txt")
    if not os.path.exists(lyrics_path):
        print(f"  SKIP {name} (no lyrics.txt — nothing to align)")
        return "skip"

    vocals_path = None
    for candidate in ("vocals.wav", "vocals.mp3"):
        p = os.path.join(stems_dir, candidate)
        if os.path.exists(p):
            vocals_path = p
            break
    if vocals_path is None:
        print(f"  SKIP {name} (no vocals stem)")
        return "skip"

    model, dictionary = get_model(int8=int8)

    raw_lines = [l.strip() for l in open(lyrics_path).read().split("\n") if l.strip()]
    lines = []
    for text in raw_lines:
        words = normalize_words(text, dictionary)
        if words:
            lines.append({"text": text, "words": words})
    if not lines:
        print(f"  FAIL {name} (no alignable words in lyrics.txt)")
        return "fail"

    waveform = load_vocals(vocals_path)
    duration = waveform.size(1) / SAMPLE_RATE
    print(f"  PROCESSING {name} ({duration:.0f}s, {len(lines)} lines)...")

    emission = compute_emission(model, waveform)
    seconds_per_frame = duration / emission.size(1)

    def build_segments(line_list):
        """Align a line list against the (already computed) emission."""
        # Star between lines lets instrumental breaks be skipped rather than absorbed
        # into a neighbouring line's duration.
        units = []
        for idx, line in enumerate(line_list):
            if idx:
                units.append(("star", [dictionary["*"]]))
            for word in line["words"]:
                units.append(("word", [dictionary[c] for c in word]))
        return _regroup(align(emission, units, dictionary), line_list, seconds_per_frame)

    try:
        segments = build_segments(lines)
        # The audio, not the lyrics source, decides how many times a line repeats.
        # Re-aligning is cheap here: the model forward is done, this is Viterbi only.
        corrected = correct_repeat_counts(
            waveform, lines, segments, seconds_per_frame
        )
        if corrected:
            lines = corrected
            segments = build_segments(lines)
    except Exception as e:
        print(f"  FAIL {name} ({type(e).__name__}: {e})")
        return "fail"

    if not segments:
        print(f"  FAIL {name} (alignment produced no spans)")
        return "fail"

    segments = redistribute_repeats(segments)
    segments = reanchor_outliers(segments)

    # Monotonicity is guaranteed by Viterbi, but guard against zero/negative spans.
    for seg in segments:
        if seg["end"] <= seg["start"]:
            seg["end"] = round(seg["start"] + 0.5, 2)

    with open(out_path, "w") as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)

    longest = max(s["end"] - s["start"] for s in segments)
    covered = segments[-1]["end"] - segments[0]["start"]
    print(f"  OK {name} ({len(segments)} lines, {segments[0]['start']:.0f}s-"
          f"{segments[-1]['end']:.0f}s of {duration:.0f}s, longest line {longest:.1f}s)")
    return "ok"


def repair_song(stems_dir):
    """Re-run only the cheap post-passes over an existing lyrics_timed.json.

    The expensive part of alignment is the model forward, and its output is already
    baked into the word timings on disk. Repairing a library therefore costs
    milliseconds a song rather than the ~2 minutes a full realign takes on CPU.
    """
    name = os.path.basename(stems_dir.rstrip("/"))
    path = os.path.join(stems_dir, "lyrics_timed.json")
    if not os.path.exists(path):
        return "skip"
    try:
        segments = json.load(open(path))
    except Exception:
        print(f"  FAIL {name} (unreadable lyrics_timed.json)")
        return "fail"
    if not segments or not any(s.get("words") for s in segments):
        print(f"  SKIP {name} (no word timings to repair)")
        return "skip"

    before = max(s["end"] - s["start"] for s in segments)
    segments = reanchor_outliers(segments)
    after = max(s["end"] - s["start"] for s in segments)

    if after < before - 0.05:
        with open(path, "w") as f:
            json.dump(segments, f, indent=2, ensure_ascii=False)
        print(f"  OK {name} (longest line {before:.1f}s -> {after:.1f}s)")
        return "ok"
    print(f"  SKIP {name} (longest line {before:.1f}s, nothing to re-anchor)")
    return "skip"


def main():
    force = "--force" in sys.argv
    int8 = "--int8" in sys.argv
    repair = "--repair" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--force", "--int8", "--repair")]

    if not args:
        print(__doc__)
        sys.exit(1)

    if repair:
        root = args[1] if args[0] == "--batch" and len(args) > 1 else None
        if args[0] == "--batch":
            root = root or os.path.expanduser("~/Music/karaoke/htdemucs")
            results = {"ok": 0, "skip": 0, "fail": 0}
            for name in sorted(os.listdir(root)):
                song_dir = os.path.join(root, name)
                if os.path.isdir(song_dir):
                    results[repair_song(song_dir)] += 1
            print(f"\n=== Repaired: {results['ok']}  Skipped: {results['skip']}  "
                  f"Failed: {results['fail']} ===")
        else:
            repair_song(args[0])
        return

    if args[0] == "--batch":
        root = args[1] if len(args) > 1 else os.path.expanduser("~/Music/karaoke/htdemucs")
        results = {"ok": 0, "skip": 0, "fail": 0}
        for name in sorted(os.listdir(root)):
            song_dir = os.path.join(root, name)
            if not os.path.isdir(song_dir):
                continue
            try:
                results[process_song(song_dir, force, int8)] += 1
            except Exception as e:
                print(f"  FAIL {name} ({type(e).__name__}: {e})")
                results["fail"] += 1
        print(f"\n=== Aligned: {results['ok']}  Skipped: {results['skip']}  "
              f"Failed: {results['fail']} ===")
    else:
        process_song(args[0], force, int8)


if __name__ == "__main__":
    main()
