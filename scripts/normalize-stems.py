#!/usr/bin/env python3
"""
Normalize stem volumes for consistent loudness across songs.
Analyzes combined RMS of all stems and applies uniform gain.

Usage:
  python3 normalize-stems.py /path/to/song_dir          # Normalize one song
  python3 normalize-stems.py /path/to/htdemucs/          # Normalize all songs in dir
  python3 normalize-stems.py /path/to/htdemucs/ --check  # Check levels without changing
"""

import numpy as np
import wave
import os
import sys

TARGET_RMS = 0.12  # Target combined RMS level (0.0 - 1.0)
STEM_NAMES = ['vocals', 'drums', 'bass', 'other']


def read_wav(path):
    with wave.open(path, 'r') as f:
        params = f.getparams()
        data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32)
    return data, params


def write_wav(path, data, params):
    with wave.open(path, 'w') as f:
        f.setparams(params)
        f.writeframes(data.clip(-32767, 32767).astype(np.int16).tobytes())


def get_song_rms(song_dir):
    """Calculate combined RMS of all stems mixed together."""
    combined = None
    for stem in STEM_NAMES:
        path = os.path.join(song_dir, f'{stem}.wav')
        if not os.path.exists(path):
            continue
        data, _ = read_wav(path)
        if combined is None:
            combined = data.copy()
        else:
            minlen = min(len(combined), len(data))
            combined = combined[:minlen] + data[:minlen]

    if combined is None:
        return 0.0
    return np.sqrt(np.mean(combined ** 2)) / 32767


def normalize_song(song_dir, check_only=False):
    """Normalize all stems in a song directory."""
    song_name = os.path.basename(song_dir)

    # Check if stems exist
    stems = {}
    for stem in STEM_NAMES:
        path = os.path.join(song_dir, f'{stem}.wav')
        if os.path.exists(path):
            stems[stem] = path

    if not stems:
        return None

    # Calculate combined RMS
    current_rms = get_song_rms(song_dir)
    if current_rms < 0.001:
        print(f"  {song_name}: SKIP (silent)")
        return None

    gain = TARGET_RMS / current_rms

    # Check peak to prevent clipping
    max_peak = 0
    for path in stems.values():
        data, _ = read_wav(path)
        max_peak = max(max_peak, np.max(np.abs(data)))

    if max_peak * gain > 32000:
        gain = 32000 / max_peak

    new_rms = current_rms * gain

    if check_only:
        status = "OK" if abs(current_rms - TARGET_RMS) / TARGET_RMS < 0.1 else "NEEDS NORM"
        print(f"  {song_name:45s} RMS={current_rms:.4f} → {new_rms:.4f} gain={gain:.2f}x  [{status}]")
        return gain

    # Apply gain to all stems
    for stem, path in stems.items():
        data, params = read_wav(path)
        normalized = data * gain
        write_wav(path, normalized, params)

    print(f"  {song_name:45s} RMS={current_rms:.4f} → {new_rms:.4f} gain={gain:.2f}x  [NORMALIZED]")
    return gain


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 normalize-stems.py <song_dir_or_parent> [--check]")
        sys.exit(1)

    path = sys.argv[1]
    check_only = "--check" in sys.argv

    # Determine if single song or directory of songs
    if os.path.exists(os.path.join(path, 'vocals.wav')):
        # Single song directory
        print(f"{'Checking' if check_only else 'Normalizing'}: {path}")
        normalize_song(path, check_only)
    else:
        # Parent directory containing multiple songs
        songs = sorted([d for d in os.listdir(path)
                       if os.path.isdir(os.path.join(path, d))
                       and os.path.exists(os.path.join(path, d, 'vocals.wav'))])

        print(f"{'Checking' if check_only else 'Normalizing'} {len(songs)} songs (target RMS={TARGET_RMS}):")
        print()

        for song in songs:
            normalize_song(os.path.join(path, song), check_only)

        print(f"\n{'Check' if check_only else 'Normalization'} complete.")


if __name__ == "__main__":
    main()
