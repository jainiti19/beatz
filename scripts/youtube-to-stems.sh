#!/bin/bash
# Usage: ./youtube-to-stems.sh <youtube-url> [song-name]
# Downloads audio from YouTube, separates with Demucs, transcribes lyrics, pushes to device

set -e

URL="$1"
NAME="$2"

if [ -z "$URL" ]; then
  echo "Usage: $0 <youtube-url> [song-name]"
  exit 1
fi

source ~/demucs-env/bin/activate

WORK_DIR=~/Music/beatz_pipeline
mkdir -p "$WORK_DIR"

# Step 1: Download
echo "=== Step 1: Downloading ==="
rm -f "$WORK_DIR/download.mp3"
yt-dlp --js-runtimes nodejs -x --audio-format mp3 --audio-quality 0 --no-playlist \
  -o "$WORK_DIR/download.mp3" "$URL" 2>&1 | tail -3

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

if $ADB devices 2>/dev/null | grep -q "device$"; then
  $ADB shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/stems/$NAME"
  for stem in vocals drums bass other; do
    $ADB shell "mkdir -p /sdcard/Music/karaoke/htdemucs/$NAME"
    $ADB push "$FINAL_DIR/$stem.wav" "/sdcard/Music/karaoke/htdemucs/${NAME}/$stem.wav" 2>/dev/null
    $ADB shell "cat /sdcard/Music/karaoke/htdemucs/${NAME}/$stem.wav | run-as com.beatz.app tee /data/data/com.beatz.app/files/stems/${NAME}/$stem.wav > /dev/null"
  done
  # Push lyrics
  if [ -f "$FINAL_DIR/lyrics.txt" ]; then
    $ADB shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/lyrics"
    $ADB push "$FINAL_DIR/lyrics.txt" "/sdcard/lyrics_temp.txt" 2>/dev/null
    $ADB shell "cat /sdcard/lyrics_temp.txt | run-as com.beatz.app tee /data/data/com.beatz.app/files/lyrics/${NAME}.txt > /dev/null"
  fi
  echo "Done! Open Beatz → Jamming Mode → $NAME"
else
  echo "No device. Stems at: $FINAL_DIR"
fi

rm -f "$WORK_DIR/download.mp3"
rm -rf "$WORK_DIR/separated"
