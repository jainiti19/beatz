#!/bin/bash
# Batch fetch Genius lyrics for all songs missing lyrics.txt
# Usage: ./scripts/batch-fetch-lyrics.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STEMS_DIR=~/Music/karaoke/htdemucs
FETCH="$SCRIPT_DIR/fetch-lyrics.py"

source ~/demucs-env/bin/activate

total=0
fetched=0
skipped=0
failed=0

for song_dir in "$STEMS_DIR"/*/; do
  name=$(basename "$song_dir")

  # Skip duplicate/long-named dirs
  [[ "$name" == *"["* ]] && continue
  [[ ${#name} -gt 50 ]] && continue

  total=$((total + 1))

  # Skip if lyrics already exist and are good (>50 chars)
  if [ -f "$song_dir/lyrics.txt" ]; then
    size=$(wc -c < "$song_dir/lyrics.txt")
    if [ "$size" -gt 50 ]; then
      echo "SKIP $name (already has lyrics)"
      skipped=$((skipped + 1))
      continue
    fi
  fi

  echo "FETCH $name ..."
  python3 "$FETCH" "$name" "$song_dir/lyrics.txt"

  if [ -f "$song_dir/lyrics.txt" ]; then
    size=$(wc -c < "$song_dir/lyrics.txt")
    if [ "$size" -gt 20 ]; then
      fetched=$((fetched + 1))
      echo "  OK ($size chars)"
    else
      rm -f "$song_dir/lyrics.txt"
      failed=$((failed + 1))
      echo "  FAIL (too short, removed)"
    fi
  else
    failed=$((failed + 1))
    echo "  FAIL (no result)"
  fi
done

echo ""
echo "=== Results ==="
echo "Total: $total"
echo "Already had lyrics: $skipped"
echo "Fetched new: $fetched"
echo "Failed: $failed"
