#!/bin/bash
# Watches the device for YouTube URL requests from the Beatz app
# and automatically processes them with Demucs.
# Usage: ./watch-youtube-queue.sh

ADB=~/Android/platform-tools/adb
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Watching for YouTube URL requests from Beatz app..."
echo "Press Ctrl+C to stop"
echo ""

while true; do
  # Check if device is connected
  if ! $ADB devices 2>/dev/null | grep -q "device$"; then
    sleep 5
    continue
  fi

  # Check for queued URLs
  QUEUE=$($ADB shell "run-as com.beatz.app ls /data/data/com.beatz.app/files/youtube_queue/ 2>/dev/null" | tr -d '\r' | grep "request_")

  for request in $QUEUE; do
    URL=$($ADB shell "run-as com.beatz.app cat /data/data/com.beatz.app/files/youtube_queue/$request" | tr -d '\r')

    if [ -n "$URL" ]; then
      echo "=== Processing: $URL ==="
      "$SCRIPT_DIR/youtube-to-stems.sh" "$URL"

      # Remove processed request
      $ADB shell "run-as com.beatz.app rm /data/data/com.beatz.app/files/youtube_queue/$request"
      echo ""
    fi
  done

  sleep 5
done
