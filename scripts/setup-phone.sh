#!/bin/bash
# BeatznBox Phone Setup Script
# Usage: ./scripts/setup-phone.sh
# Installs APK + pushes all songs (stems + lyrics) to a connected phone

set -e

ADB=~/Android/platform-tools/adb
STEMS_DIR=~/Music/karaoke/htdemucs
APK=app/build/outputs/apk/debug/app-debug.apk

echo "============================================"
echo "  BeatznBox Phone Setup"
echo "============================================"
echo ""

# Step 1: Check phone
echo "Checking for connected phone..."
$ADB kill-server 2>/dev/null
sleep 2
DEVICE=$($ADB devices 2>/dev/null | grep -v emulator | grep "device$" | head -1 | awk '{print $1}')

if [ -z "$DEVICE" ]; then
  echo "ERROR: No phone detected!"
  echo ""
  echo "Make sure:"
  echo "  1. Phone is plugged in via USB"
  echo "  2. USB debugging is enabled (Developer Options)"
  echo "  3. USB mode is set to 'File Transfer'"
  echo "  4. Approve the USB debugging prompt on the phone"
  exit 1
fi

echo "Found device: $DEVICE"
MODEL=$($ADB -s "$DEVICE" shell getprop ro.product.model | tr -d '\r')
echo "Phone: $MODEL"
echo ""

# Step 2: Install APK
if [ -f "$APK" ]; then
  echo "Installing BeatznBox..."
  $ADB -s "$DEVICE" install -r "$APK"
  echo ""
else
  echo "APK not found at $APK"
  echo "Building..."
  ./gradlew assembleDebug 2>&1 | tail -3
  $ADB -s "$DEVICE" install -r "$APK"
  echo ""
fi

# Step 3: Count songs
SONG_COUNT=$(ls -d "$STEMS_DIR"/*/ 2>/dev/null | wc -l)
echo "Found $SONG_COUNT songs to push"
echo ""

# Step 4: Push all stems
PUSHED=0
FAILED=0

$ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/stems" 2>/dev/null
$ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/lyrics" 2>/dev/null

for dir in "$STEMS_DIR"/*/; do
  NAME=$(basename "$dir")
  PUSHED=$((PUSHED + 1))
  echo "[$PUSHED/$SONG_COUNT] $NAME"

  # Check if all 4 stems exist
  if [ ! -f "$dir/vocals.wav" ] || [ ! -f "$dir/drums.wav" ] || [ ! -f "$dir/bass.wav" ] || [ ! -f "$dir/other.wav" ]; then
    echo "  SKIP (missing stems)"
    FAILED=$((FAILED + 1))
    continue
  fi

  # Create dir on phone
  $ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/stems/$NAME" 2>/dev/null

  # Push stems
  OK=true
  for stem in vocals drums bass other; do
    $ADB -s "$DEVICE" push "$dir/$stem.wav" "/data/local/tmp/${stem}.wav" 2>/dev/null && \
    $ADB -s "$DEVICE" shell "cat /data/local/tmp/${stem}.wav | run-as com.beatz.app sh -c 'cat > /data/data/com.beatz.app/files/stems/${NAME}/${stem}.wav'" 2>/dev/null && \
    $ADB -s "$DEVICE" shell "rm /data/local/tmp/${stem}.wav" 2>/dev/null
    if [ $? -ne 0 ]; then
      OK=false
      break
    fi
  done

  # Push lyrics if available
  if [ -f "$dir/lyrics.txt" ] && [ -s "$dir/lyrics.txt" ]; then
    $ADB -s "$DEVICE" push "$dir/lyrics.txt" "/data/local/tmp/l.txt" 2>/dev/null && \
    $ADB -s "$DEVICE" shell "cat /data/local/tmp/l.txt | run-as com.beatz.app sh -c 'cat > /data/data/com.beatz.app/files/lyrics/${NAME}.txt'" 2>/dev/null && \
    $ADB -s "$DEVICE" shell "rm /data/local/tmp/l.txt" 2>/dev/null
    echo "  + lyrics"
  fi

  if [ "$OK" = true ]; then
    echo "  OK"
  else
    echo "  FAILED"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo "  Phone: $MODEL"
echo "  Songs pushed: $((PUSHED - FAILED))/$SONG_COUNT"
if [ $FAILED -gt 0 ]; then
  echo "  Failed: $FAILED"
fi
echo ""
echo "  Open BeatznBox on the phone and enjoy!"
echo "============================================"

# Launch app
$ADB -s "$DEVICE" shell am start -n com.beatz.app/.MainActivity 2>/dev/null
