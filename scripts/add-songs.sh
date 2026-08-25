#!/bin/bash
# Add songs end to end: download, separate, normalise, fetch lyrics, align.
#
# Reads a manifest of  folder_name | youtube search | lyrics search  and works
# through it, skipping any song whose stems already exist so an interrupted run
# can simply be restarted.
#
# Separation uses htdemucs_ft to match the rest of the library — four specialist
# models, roughly 2x realtime, so budget ~10 min for a 5 minute song. Pass
# --fast to use plain htdemucs instead (~2.5 min, slightly muddier stems).
#
# Usage: ./scripts/add-songs.sh manifest.txt [--fast]

set -uo pipefail

MANIFEST="${1:?usage: add-songs.sh manifest.txt [--fast]}"
MODEL=htdemucs_ft
[ "${2:-}" = "--fast" ] && MODEL=htdemucs

VENV=~/demucs-env/bin
SRC=~/Music/karaoke/htdemucs
WORK=~/Music/beatz_pipeline
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$WORK" "$SRC"

total=$(grep -cvE '^\s*(#|$)' "$MANIFEST")
n=0
ok=0; failed=0; skipped=0

while IFS='|' read -r NAME YT LYR; do
  case "$NAME" in ''|\#*) continue;; esac
  NAME=$(echo "$NAME" | xargs); YT=$(echo "$YT" | xargs); LYR=$(echo "$LYR" | xargs)
  n=$((n+1))
  DIR="$SRC/$NAME"

  echo ""
  echo "=========================================================="
  echo "[$n/$total] $NAME"
  echo "=========================================================="

  if [ -f "$DIR/vocals.wav" ]; then
    echo "  stems already exist — skipping separation"
  else
    echo "  [1/4] downloading: $YT"
    rm -f "$WORK/dl.mp3"
    "$VENV/yt-dlp" --js-runtimes node -x --audio-format mp3 --audio-quality 0 \
      --no-playlist -o "$WORK/dl.mp3" "ytsearch1:$YT" >/dev/null 2>&1
    if [ ! -f "$WORK/dl.mp3" ]; then
      echo "  FAIL: download produced nothing"; failed=$((failed+1)); continue
    fi
    DUR=$("$VENV/python" -c "import subprocess,sys;print(subprocess.run(['ffprobe','-v','quiet','-show_entries','format=duration','-of','csv=p=0','$WORK/dl.mp3'],capture_output=True,text=True).stdout.strip()[:5])" 2>/dev/null)
    echo "        got ${DUR}s of audio"

    echo "  [2/4] separating with $MODEL (this is the slow part)"
    rm -rf "$WORK/sep"
    "$VENV/python" -m demucs -n "$MODEL" --out "$WORK/sep" "$WORK/dl.mp3" >/dev/null 2>&1
    STEM=$(ls -td "$WORK/sep/$MODEL/"*/ 2>/dev/null | head -1)
    if [ -z "$STEM" ]; then
      echo "  FAIL: separation produced nothing"; failed=$((failed+1)); continue
    fi
    mkdir -p "$DIR"
    cp "$STEM"/*.wav "$DIR/"
    "$VENV/python" "$SCRIPT_DIR/normalize-stems.py" "$DIR" >/dev/null 2>&1
    echo "        stems written + normalised"
  fi

  echo "  [3/4] lyrics: $LYR"
  if ! "$VENV/python" "$SCRIPT_DIR/fetch-lyrics-lrclib.py" "$LYR" "$DIR/lyrics.txt"; then
    echo "        no usable lyrics — stems are still fine, words need doing by hand"
    ok=$((ok+1)); continue
  fi

  echo "  [4/4] aligning"
  if "$VENV/python" "$SCRIPT_DIR/align-lyrics.py" "$DIR" --force >/dev/null 2>&1; then
    LINES=$("$VENV/python" -c "import json;print(len(json.load(open('$DIR/lyrics_timed.json'))))" 2>/dev/null)
    echo "        aligned ${LINES} lines"
    ok=$((ok+1))
  else
    echo "        alignment failed — words present, timing missing"
    ok=$((ok+1))
  fi
done < "$MANIFEST"

echo ""
echo "=========================================================="
echo "done: $ok processed, $failed failed, $skipped skipped"
echo "next: ./scripts/prepare-web.sh && ./scripts/deploy-web.sh"
echo "=========================================================="
