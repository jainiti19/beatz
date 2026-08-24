#!/usr/bin/env python3
"""
Generate lyrics_timed.json from Whisper timestamps + Genius lyrics text.

Strategy:
- Run Whisper on vocals.wav to get segment timestamps
- If Genius lyrics.txt exists, use its text (better quality) mapped to Whisper timing
- Otherwise, use Whisper's own text with timestamps

Usage: python3 generate-timed-lyrics.py <stems_dir> [--force]
       python3 generate-timed-lyrics.py --batch <htdemucs_dir> [--force]
"""

import sys
import os
import json
import re


def load_whisper_segments(vocals_path):
    """Transcribe vocals and return segments with timestamps."""
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(vocals_path, word_timestamps=True)
    segments = []
    for seg in result["segments"]:
        text = seg["text"].strip()
        if not text:
            continue
        # Try to split long segments using word timestamps
        words = seg.get("words", [])
        if words and len(words) > 4:
            # Group words into ~3-5 word chunks for finer-grained lines
            chunk_size = max(3, min(5, len(words) // 2))
            for j in range(0, len(words), chunk_size):
                chunk = words[j:j + chunk_size]
                chunk_text = " ".join(w.get("word", w.get("text", "")).strip() for w in chunk).strip()
                if chunk_text:
                    segments.append({
                        "start": round(chunk[0].get("start", seg["start"]), 2),
                        "end": round(chunk[-1].get("end", seg["end"]), 2),
                        "text": chunk_text
                    })
        else:
            segments.append({
                "start": round(seg["start"], 2),
                "end": round(seg["end"], 2),
                "text": text
            })
    return segments


def load_genius_lyrics(lyrics_path):
    """Load Genius lyrics and split into non-empty lines."""
    with open(lyrics_path, "r") as f:
        text = f.read()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return lines


def merge_lyrics(whisper_segments, genius_lines):
    """Map Genius lyrics text onto Whisper timestamps.

    If line counts are similar, map 1:1.
    If Genius has more lines, group them proportionally.
    If Whisper has more segments, merge adjacent segments.
    """
    ws_count = len(whisper_segments)
    gl_count = len(genius_lines)

    if ws_count == 0 or gl_count == 0:
        return whisper_segments

    ratio = gl_count / ws_count

    if 0.7 <= ratio <= 1.3:
        # Close enough — map 1:1, truncating the longer list
        merged = []
        for i in range(min(ws_count, gl_count)):
            merged.append({
                "start": whisper_segments[i]["start"],
                "end": whisper_segments[i]["end"],
                "text": genius_lines[i]
            })
        # If genius has leftover lines, append to last segment
        if gl_count > ws_count:
            for i in range(ws_count, gl_count):
                merged[-1]["text"] += "\n" + genius_lines[i]
        return merged

    elif ratio > 1.3:
        # More genius lines than whisper segments — group genius lines per segment
        merged = []
        lines_per_seg = gl_count / ws_count
        for i in range(ws_count):
            start_idx = int(i * lines_per_seg)
            end_idx = int((i + 1) * lines_per_seg)
            grouped_text = "\n".join(genius_lines[start_idx:end_idx])
            merged.append({
                "start": whisper_segments[i]["start"],
                "end": whisper_segments[i]["end"],
                "text": grouped_text
            })
        return merged

    else:
        # More whisper segments than genius lines — merge adjacent whisper segments
        merged = []
        segs_per_line = ws_count / gl_count
        for i in range(gl_count):
            start_idx = int(i * segs_per_line)
            end_idx = int((i + 1) * segs_per_line)
            merged.append({
                "start": whisper_segments[start_idx]["start"],
                "end": whisper_segments[end_idx - 1]["end"],
                "text": genius_lines[i]
            })
        return merged


def process_song(stems_dir, force=False):
    """Generate lyrics_timed.json for a single song."""
    name = os.path.basename(stems_dir)
    output_path = os.path.join(stems_dir, "lyrics_timed.json")

    if os.path.exists(output_path) and not force:
        print(f"  SKIP {name} (already has timed lyrics)")
        return "skip"

    vocals_path = os.path.join(stems_dir, "vocals.wav")
    if not os.path.exists(vocals_path):
        print(f"  SKIP {name} (no vocals.wav)")
        return "skip"

    print(f"  PROCESSING {name}...")

    # Get Whisper timestamps
    segments = load_whisper_segments(vocals_path)
    if not segments:
        print(f"  FAIL {name} (no segments from Whisper)")
        return "fail"

    # Try merging with Genius lyrics
    lyrics_path = os.path.join(stems_dir, "lyrics.txt")
    if os.path.exists(lyrics_path):
        genius_lines = load_genius_lyrics(lyrics_path)
        if genius_lines:
            segments = merge_lyrics(segments, genius_lines)
            print(f"    Merged {len(genius_lines)} Genius lines with Whisper timing")

    # Validate: ensure end >= start for all segments
    for seg in segments:
        if seg["end"] < seg["start"]:
            seg["end"] = seg["start"] + 3.0

    with open(output_path, "w") as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)

    print(f"  OK {name} ({len(segments)} timed segments)")
    return "ok"


def main():
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]

    if not args:
        print("Usage: python3 generate-timed-lyrics.py <stems_dir> [--force]")
        print("       python3 generate-timed-lyrics.py --batch <htdemucs_dir> [--force]")
        sys.exit(1)

    if args[0] == "--batch":
        htdemucs_dir = args[1] if len(args) > 1 else os.path.expanduser("~/Music/karaoke/htdemucs")
        results = {"ok": 0, "skip": 0, "fail": 0}
        dirs = sorted(os.listdir(htdemucs_dir))
        for name in dirs:
            song_dir = os.path.join(htdemucs_dir, name)
            if not os.path.isdir(song_dir):
                continue
            if "[" in name or len(name) > 50:
                continue
            result = process_song(song_dir, force)
            results[result] += 1

        print(f"\n=== Results ===")
        print(f"Processed: {results['ok']}")
        print(f"Skipped: {results['skip']}")
        print(f"Failed: {results['fail']}")
    else:
        process_song(args[0], force)


if __name__ == "__main__":
    main()
