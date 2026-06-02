#!/bin/bash
# Usage: ./youtube-to-stems.sh <youtube-url> [song-name]
# Downloads audio from YouTube, separates with Demucs, pushes to emulator/device

set -e

URL="$1"
NAME="$2"

if [ -z "$URL" ]; then
  echo "Usage: $0 <youtube-url> [song-name]"
  echo "Example: $0 'https://www.youtube.com/watch?v=xxxxx' 'Tauba_Tauba'"
  exit 1
fi

# Activate Python environment
source ~/demucs-env/bin/activate

WORK_DIR=~/Music/beatz_pipeline
mkdir -p "$WORK_DIR"

# Step 1: Download audio from YouTube
echo "=== Step 1: Downloading audio ==="
DOWNLOAD_FILE="$WORK_DIR/download.%(ext)s"
yt-dlp -x --audio-format mp3 --audio-quality 0 -o "$DOWNLOAD_FILE" "$URL"

# Find the downloaded file
MP3_FILE=$(ls -t "$WORK_DIR"/download.mp3 2>/dev/null | head -1)
if [ -z "$MP3_FILE" ]; then
  echo "ERROR: Download failed"
  exit 1
fi

# Auto-detect song name from YouTube title if not provided
if [ -z "$NAME" ]; then
  NAME=$(yt-dlp --get-title "$URL" 2>/dev/null | head -1 | sed 's/[^a-zA-Z0-9 ]//g' | sed 's/ /_/g' | head -c 40)
  if [ -z "$NAME" ]; then
    NAME="youtube_song"
  fi
fi

echo "Song name: $NAME"

# Step 2: Separate with Demucs (4 stems)
echo ""
echo "=== Step 2: Separating stems with Demucs ==="
demucs -n htdemucs --out "$WORK_DIR/separated" "$MP3_FILE"

# Find the separated directory
STEM_DIR=$(ls -td "$WORK_DIR/separated/htdemucs/"*/ 2>/dev/null | head -1)
if [ -z "$STEM_DIR" ]; then
  echo "ERROR: Demucs separation failed"
  exit 1
fi

# Step 3: Copy to organized location
echo ""
echo "=== Step 3: Organizing stems ==="
FINAL_DIR=~/Music/karaoke/htdemucs/$NAME
mkdir -p "$FINAL_DIR"
cp "$STEM_DIR"/*.wav "$FINAL_DIR/"
echo "Stems saved to: $FINAL_DIR"
ls -lh "$FINAL_DIR/"

# Step 4: Push to device (if connected)
echo ""
echo "=== Step 4: Pushing to device ==="
ADB=~/Android/platform-tools/adb

if $ADB devices 2>/dev/null | grep -q "device$"; then
  # Push to app internal storage
  $ADB shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/stems/$NAME"
  for stem in vocals drums bass other; do
    if [ -f "$FINAL_DIR/$stem.wav" ]; then
      # Push to sdcard first, then copy to app storage
      $ADB push "$FINAL_DIR/$stem.wav" "/sdcard/Music/karaoke/htdemucs/${NAME}/$stem.wav"
      $ADB shell "cat /sdcard/Music/karaoke/htdemucs/${NAME}/$stem.wav | run-as com.beatz.app tee /data/data/com.beatz.app/files/stems/${NAME}/$stem.wav > /dev/null"
      echo "  Pushed $stem"
    fi
  done
  echo "Stems available in Beatz app!"
else
  echo "No device connected. Stems saved locally at: $FINAL_DIR"
  echo "Push manually later with:"
  echo "  adb push $FINAL_DIR/ /sdcard/Music/karaoke/htdemucs/$NAME/"
fi

# Cleanup
rm -f "$WORK_DIR/download.mp3"
rm -rf "$WORK_DIR/separated"

echo ""
echo "=== Done! ==="
echo "Open Beatz → Jamming Mode → $NAME"
