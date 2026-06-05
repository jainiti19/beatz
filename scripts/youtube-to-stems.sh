#!/bin/bash
# Usage: ./youtube-to-stems.sh <youtube-url> [song-name]
# Downloads audio from YouTube, separates with Demucs, transcribes lyrics, pushes to device

set -e

INPUT="$1"
NAME="$2"

if [ -z "$INPUT" ]; then
  echo "Usage: $0 <youtube-url-or-search-query> [song-name]"
  exit 1
fi

source ~/demucs-env/bin/activate

WORK_DIR=~/Music/beatz_pipeline
mkdir -p "$WORK_DIR"

# Handle search queries (prefixed with "search:")
if [[ "$INPUT" == search:* ]]; then
  QUERY="${INPUT#search:}"
  echo "=== Searching YouTube for: $QUERY ==="
  URL=$(yt-dlp --js-runtimes nodejs "ytsearch:$QUERY" --get-url --no-playlist -f bestaudio 2>/dev/null | head -1)
  if [ -z "$URL" ]; then
    echo "ERROR: No results found for '$QUERY'"
    exit 1
  fi
  # Get title for naming
  if [ -z "$NAME" ]; then
    NAME=$(yt-dlp --js-runtimes nodejs "ytsearch:$QUERY" --get-title --no-playlist 2>/dev/null | head -1 | \
      sed 's/[^a-zA-Z0-9 ]//g' | sed 's/ /_/g' | head -c 40)
    [ -z "$NAME" ] && NAME="$( echo "$QUERY" | sed 's/[^a-zA-Z0-9 ]//g' | sed 's/ /_/g' | head -c 40)"
  fi
  echo "Found: $NAME"
  # Use search URL for download
  DL_URL="ytsearch:$QUERY"
else
  URL="$INPUT"
  DL_URL="$INPUT"
fi

# Step 1: Download
echo "=== Step 1: Downloading ==="
rm -f "$WORK_DIR/download.mp3"
yt-dlp --js-runtimes nodejs -x --audio-format mp3 --audio-quality 0 --no-playlist \
  -o "$WORK_DIR/download.mp3" "$DL_URL" 2>&1 | tail -3

if [ -z "$NAME" ]; then
  NAME=$(yt-dlp --js-runtimes nodejs --get-title --no-playlist "$URL" 2>/dev/null | \
    sed 's/[^a-zA-Z0-9 ]//g' | sed 's/ /_/g' | head -c 40)
  [ -z "$NAME" ] && NAME="youtube_song"
fi
echo "Song: $NAME"

# Step 2: Demucs
echo ""
echo "=== Step 2: Separating stems ==="
rm -rf "$WORK_DIR/separated"
demucs -n htdemucs --out "$WORK_DIR/separated" "$WORK_DIR/download.mp3" 2>&1 | grep -E "100%|Separating"

STEM_DIR=$(ls -td "$WORK_DIR/separated/htdemucs/"*/ 2>/dev/null | head -1)

# Step 3: Organize
FINAL_DIR=~/Music/karaoke/htdemucs/$NAME
mkdir -p "$FINAL_DIR"
cp "$STEM_DIR"/*.wav "$FINAL_DIR/"

# Step 4: Transcribe lyrics
echo ""
echo "=== Step 3: Transcribing lyrics ==="
python3 -c "
import whisper, sys
model = whisper.load_model('base')
result = model.transcribe('$FINAL_DIR/vocals.wav')
with open('$FINAL_DIR/lyrics.txt', 'w') as f:
    for seg in result['segments']:
        f.write(seg['text'].strip() + '\n')
print(open('$FINAL_DIR/lyrics.txt').read()[:500])
" 2>&1 | grep -v "FP16" | grep -v "^$"

# Step 5: Push to device
echo ""
echo "=== Step 4: Pushing to device ==="
ADB=~/Android/platform-tools/adb

# Find a real device (not emulator)
DEVICE=$($ADB devices | grep -v emulator | grep "device$" | head -1 | awk '{print $1}')
if [ -z "$DEVICE" ]; then
  # Fall back to any connected device
  DEVICE=$($ADB devices | grep "device$" | head -1 | awk '{print $1}')
fi

if [ -n "$DEVICE" ]; then
  echo "Pushing to device: $DEVICE"
  $ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/stems/$NAME"
  for stem in vocals drums bass other; do
    if [ -f "$FINAL_DIR/$stem.wav" ]; then
      echo "  Pushing $stem.wav..."
      $ADB -s "$DEVICE" push "$FINAL_DIR/$stem.wav" "/data/local/tmp/${stem}.wav" 2>/dev/null
      $ADB -s "$DEVICE" shell "cat /data/local/tmp/${stem}.wav | run-as com.beatz.app sh -c 'cat > /data/data/com.beatz.app/files/stems/${NAME}/${stem}.wav'"
      $ADB -s "$DEVICE" shell "rm /data/local/tmp/${stem}.wav"
    fi
  done
  # Push lyrics
  if [ -f "$FINAL_DIR/lyrics.txt" ]; then
    echo "  Pushing lyrics..."
    $ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/lyrics"
    $ADB -s "$DEVICE" push "$FINAL_DIR/lyrics.txt" "/data/local/tmp/lyrics_temp.txt" 2>/dev/null
    $ADB -s "$DEVICE" shell "cat /data/local/tmp/lyrics_temp.txt | run-as com.beatz.app sh -c 'cat > /data/data/com.beatz.app/files/lyrics/${NAME}.txt'"
    $ADB -s "$DEVICE" shell "rm /data/local/tmp/lyrics_temp.txt"
  fi
  echo "Done! Open Beatz → Jamming Mode → $NAME"
else
  echo "No device. Stems at: $FINAL_DIR"
fi

rm -f "$WORK_DIR/download.mp3"
rm -rf "$WORK_DIR/separated"
