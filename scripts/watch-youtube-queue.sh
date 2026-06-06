#!/bin/bash
# Watches the device for YouTube URL requests from the Beatz app
# and automatically processes them with Demucs.
# Supports real-time status feedback to the app.
# Usage: ./watch-youtube-queue.sh

ADB=~/Android/platform-tools/adb
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

find_device() {
  $ADB devices 2>/dev/null | grep -v emulator | grep "device$" | head -1 | awk '{print $1}'
}

write_status() {
  local DEVICE="$1"
  local NAME="$2"
  local STATUS="$3"
  $ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/processing" 2>/dev/null
  echo "$STATUS" | $ADB -s "$DEVICE" shell "run-as com.beatz.app sh -c 'cat > /data/data/com.beatz.app/files/processing/${NAME}.status'" 2>/dev/null
}

clear_status() {
  local DEVICE="$1"
  local NAME="$2"
  $ADB -s "$DEVICE" shell "run-as com.beatz.app rm /data/data/com.beatz.app/files/processing/${NAME}.status" 2>/dev/null
}

echo "Watching for YouTube URL requests from Beatz app..."
echo "Press Ctrl+C to stop"
echo ""

while true; do
  DEVICE=$(find_device)
  if [ -z "$DEVICE" ]; then
    sleep 3
    continue
  fi

  # Check for queued requests
  QUEUE=$($ADB -s "$DEVICE" shell "run-as com.beatz.app ls /data/data/com.beatz.app/files/youtube_queue/ 2>/dev/null" | tr -d '\r' | grep "request_")

  for request in $QUEUE; do
    INPUT=$($ADB -s "$DEVICE" shell "run-as com.beatz.app cat /data/data/com.beatz.app/files/youtube_queue/$request" | tr -d '\r')

    if [ -n "$INPUT" ]; then
      # Determine song name for status
      if [[ "$INPUT" == search:* ]]; then
        QUERY="${INPUT#search:}"
        STATUS_NAME=$(echo "$QUERY" | sed 's/[^a-zA-Z0-9 ]//g' | sed 's/ /_/g' | head -c 30)
      else
        STATUS_NAME="song_$(echo "$request" | grep -o '[0-9]*')"
      fi

      echo "=== Processing: $INPUT ==="

      # Write status: downloading
      write_status "$DEVICE" "$STATUS_NAME" "downloading"

      source ~/demucs-env/bin/activate

      # Step 1: Resolve name and download
      WORK_DIR=~/Music/beatz_pipeline
      mkdir -p "$WORK_DIR"
      rm -f "$WORK_DIR/download.mp3"

      if [[ "$INPUT" == search:* ]]; then
        QUERY="${INPUT#search:}"
        DL_URL="ytsearch:$QUERY"
        SONG_NAME=$(yt-dlp --js-runtimes nodejs "ytsearch:$QUERY" --get-title --no-playlist 2>/dev/null | head -1 | \
          sed 's/[^a-zA-Z0-9 ]//g' | sed 's/ /_/g' | head -c 40)
        [ -z "$SONG_NAME" ] && SONG_NAME="$STATUS_NAME"
      else
        DL_URL="$INPUT"
        SONG_NAME=$(yt-dlp --js-runtimes nodejs --get-title --no-playlist "$INPUT" 2>/dev/null | \
          sed 's/[^a-zA-Z0-9 ]//g' | sed 's/ /_/g' | head -c 40)
        [ -z "$SONG_NAME" ] && SONG_NAME="youtube_song"
      fi

      # Update status with resolved name
      write_status "$DEVICE" "$STATUS_NAME" "downloading:$SONG_NAME"

      yt-dlp --js-runtimes nodejs -x --audio-format mp3 --audio-quality 0 --no-playlist \
        -o "$WORK_DIR/download.mp3" "$DL_URL" 2>&1 | tail -1

      if [ ! -f "$WORK_DIR/download.mp3" ]; then
        write_status "$DEVICE" "$STATUS_NAME" "error:Download failed"
        $ADB -s "$DEVICE" shell "run-as com.beatz.app rm /data/data/com.beatz.app/files/youtube_queue/$request" 2>/dev/null
        sleep 3
        clear_status "$DEVICE" "$STATUS_NAME"
        continue
      fi

      # Step 2: Demucs
      write_status "$DEVICE" "$STATUS_NAME" "separating:$SONG_NAME"
      rm -rf "$WORK_DIR/separated"
      demucs -n htdemucs --out "$WORK_DIR/separated" "$WORK_DIR/download.mp3" 2>&1 | grep "100%" || true

      STEM_DIR=$(ls -td "$WORK_DIR/separated/htdemucs/"*/ 2>/dev/null | head -1)
      if [ -z "$STEM_DIR" ]; then
        write_status "$DEVICE" "$STATUS_NAME" "error:Separation failed"
        $ADB -s "$DEVICE" shell "run-as com.beatz.app rm /data/data/com.beatz.app/files/youtube_queue/$request" 2>/dev/null
        sleep 3
        clear_status "$DEVICE" "$STATUS_NAME"
        continue
      fi

      FINAL_DIR=~/Music/karaoke/htdemucs/$SONG_NAME
      mkdir -p "$FINAL_DIR"
      cp "$STEM_DIR"/*.wav "$FINAL_DIR/"

      # Step 3: Push to phone
      write_status "$DEVICE" "$STATUS_NAME" "pushing:$SONG_NAME"

      DEVICE=$(find_device)
      if [ -n "$DEVICE" ]; then
        $ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/stems/$SONG_NAME"
        for stem in vocals drums bass other; do
          if [ -f "$FINAL_DIR/$stem.wav" ]; then
            $ADB -s "$DEVICE" push "$FINAL_DIR/$stem.wav" "/data/local/tmp/${stem}.wav" 2>/dev/null
            $ADB -s "$DEVICE" shell "cat /data/local/tmp/${stem}.wav | run-as com.beatz.app sh -c 'cat > /data/data/com.beatz.app/files/stems/${SONG_NAME}/${stem}.wav'" 2>/dev/null
            $ADB -s "$DEVICE" shell "rm /data/local/tmp/${stem}.wav" 2>/dev/null
          fi
        done
        echo "Pushed: $SONG_NAME"
      fi

      # Cleanup
      clear_status "$DEVICE" "$STATUS_NAME"
      $ADB -s "$DEVICE" shell "run-as com.beatz.app rm /data/data/com.beatz.app/files/youtube_queue/$request" 2>/dev/null
      rm -f "$WORK_DIR/download.mp3"
      rm -rf "$WORK_DIR/separated"
      echo "Done: $SONG_NAME"
      echo ""
    fi
  done

  sleep 2
done
