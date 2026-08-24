#!/bin/bash
# Push forced-aligned lyrics_timed.json to every song already on the phone.
#
# The other push scripts copy stems and lyrics.txt but never the timings, so the
# app fell back to line-level highlighting even for songs that had word-level
# data sitting on the laptop. These files are a few KB each — this takes seconds,
# unlike a stem push.
#
# Usage: ./scripts/push-timed-lyrics.sh

ADB=~/Android/platform-tools/adb
SRC=~/Music/karaoke/htdemucs
PKG=com.beatznbox.app

DEVICE=$($ADB devices | grep -v emulator | grep "device$" | head -1 | awk '{print $1}')
if [ -z "$DEVICE" ]; then
  echo "No phone connected."
  exit 1
fi
echo "Phone: $DEVICE"

ON_PHONE=$($ADB -s "$DEVICE" shell "run-as $PKG ls /data/data/$PKG/files/stems/ 2>/dev/null" | tr -d '\r')
if [ -z "$ON_PHONE" ]; then
  echo "No songs on the phone yet — push stems first (setup-phone.sh)."
  exit 1
fi

pushed=0; noword=0; missing=0
for NAME in $ON_PHONE; do
  SRCFILE="$SRC/$NAME/lyrics_timed.json"
  if [ ! -f "$SRCFILE" ]; then
    missing=$((missing + 1)); continue
  fi
  # Report whether this one actually carries word-level timings, so the count
  # reflects how many songs will really sweep rather than just highlight lines.
  if grep -q '"words"' "$SRCFILE"; then :; else noword=$((noword + 1)); fi

  $ADB -s "$DEVICE" push "$SRCFILE" /data/local/tmp/lt.json >/dev/null 2>&1
  $ADB -s "$DEVICE" shell "cat /data/local/tmp/lt.json | run-as $PKG sh -c 'cat > /data/data/$PKG/files/stems/$NAME/lyrics_timed.json'" 2>/dev/null
  $ADB -s "$DEVICE" shell "rm /data/local/tmp/lt.json" 2>/dev/null
  pushed=$((pushed + 1))
done

echo ""
echo "Pushed timings: $pushed   (of those, line-level only: $noword)"
echo "No timings on laptop: $missing"
