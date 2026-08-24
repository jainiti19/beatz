#!/bin/bash
# Push all ready Kishore Kumar songs to phone (skips already-pushed ones)
ADB=~/Android/platform-tools/adb
DEVICE=$($ADB devices | grep -v emulator | grep "device$" | head -1 | awk '{print $1}')
PKG=com.beatznbox.app

if [ -z "$DEVICE" ]; then
  echo "No phone connected!"
  exit 1
fi

echo "Phone: $DEVICE"

SONGS=(
  Pal_Pal_Dil_Ke_Paas Mere_Sapno_Ki_Rani Roop_Tera_Mastana
  Yeh_Sham_Mastani Kuch_Toh_Log_Kahenge Rim_Jhim_Gire_Sawan
  O_Mere_Dil_Ke_Chain Ye_Jo_Mohabbat_Hai Chingari_Koi_Bhadke
  Phoolon_Ke_Rang_Se Ek_Ladki_Bheegi_Bhaagi_Si Mere_Naina_Sawan_Bhadon
  Zindagi_Ek_Safar Yeh_Jeevan_Hai Aa_Chal_Ke_Tujhe
  Chalte_Chalte Dil_Kya_Kare Hume_Tumse_Pyar_Kitna
  Sagar_Kinare Agar_Tum_Na_Hote
)

PUSHED=0
SKIPPED=0

for NAME in "${SONGS[@]}"; do
  DIR=~/Music/karaoke/htdemucs/$NAME
  if [ ! -f "$DIR/vocals.wav" ]; then
    continue  # not ready yet
  fi

  # Check if already on phone
  ON_PHONE=$($ADB -s "$DEVICE" shell "run-as $PKG ls /data/data/$PKG/files/stems/$NAME/vocals.wav 2>/dev/null" 2>/dev/null)
  if [ -n "$ON_PHONE" ]; then
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  echo "Pushing $NAME..."
  $ADB -s "$DEVICE" shell "run-as $PKG mkdir -p /data/data/$PKG/files/stems/$NAME" 2>/dev/null
  for stem in vocals drums bass other; do
    $ADB -s "$DEVICE" push "$DIR/$stem.wav" "/data/local/tmp/${stem}.wav" 2>/dev/null
    $ADB -s "$DEVICE" shell "cat /data/local/tmp/${stem}.wav | run-as $PKG sh -c 'cat > /data/data/$PKG/files/stems/${NAME}/${stem}.wav'" 2>/dev/null
    $ADB -s "$DEVICE" shell "rm /data/local/tmp/${stem}.wav" 2>/dev/null
  done
  if [ -f "$DIR/lyrics.txt" ] && [ -s "$DIR/lyrics.txt" ]; then
    $ADB -s "$DEVICE" shell "run-as $PKG mkdir -p /data/data/$PKG/files/lyrics" 2>/dev/null
    $ADB -s "$DEVICE" push "$DIR/lyrics.txt" "/data/local/tmp/l.txt" 2>/dev/null
    $ADB -s "$DEVICE" shell "cat /data/local/tmp/l.txt | run-as $PKG sh -c 'cat > /data/data/$PKG/files/lyrics/${NAME}.txt'" 2>/dev/null
    $ADB -s "$DEVICE" shell "rm /data/local/tmp/l.txt" 2>/dev/null
  fi
  PUSHED=$((PUSHED + 1))
done

echo ""
echo "Pushed: $PUSHED new, Skipped: $SKIPPED already on phone"
