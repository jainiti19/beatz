#!/bin/bash
# Batch process YouTube URLs: download + demucs + push to phone
# Usage: ./batch-process.sh

set -e
source ~/demucs-env/bin/activate

ADB=~/Android/platform-tools/adb
DEVICE=$($ADB devices | grep -v emulator | grep "device$" | head -1 | awk '{print $1}')
WORK_DIR=~/Music/beatz_pipeline
DEST_DIR=~/Music/karaoke/htdemucs

process_song() {
    local URL="$1"
    local NAME="$2"
    local SONG_WORK="$WORK_DIR/$NAME"

    echo "[$NAME] Starting..."
    mkdir -p "$SONG_WORK"

    # Download
    echo "[$NAME] Downloading..."
    yt-dlp --js-runtimes nodejs -x --audio-format mp3 --audio-quality 0 --no-playlist \
        -o "$SONG_WORK/audio.mp3" "$URL" 2>&1 | tail -1

    # Demucs
    echo "[$NAME] Separating stems..."
    demucs -n htdemucs --out "$SONG_WORK/separated" "$SONG_WORK/audio.mp3" 2>&1 | grep -E "100%|Separating" || true

    # Copy stems
    STEM_DIR=$(ls -td "$SONG_WORK/separated/htdemucs/"*/ 2>/dev/null | head -1)
    if [ -z "$STEM_DIR" ]; then
        echo "[$NAME] ERROR: No stems produced"
        return 1
    fi

    FINAL_DIR="$DEST_DIR/$NAME"
    mkdir -p "$FINAL_DIR"
    cp "$STEM_DIR"/*.wav "$FINAL_DIR/"

    # Push to phone
    if [ -n "$DEVICE" ]; then
        echo "[$NAME] Pushing to phone..."
        $ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/stems/$NAME"
        for stem in vocals drums bass other; do
            if [ -f "$FINAL_DIR/$stem.wav" ]; then
                $ADB -s "$DEVICE" push "$FINAL_DIR/$stem.wav" "/data/local/tmp/${stem}.wav" 2>/dev/null
                $ADB -s "$DEVICE" shell "cat /data/local/tmp/${stem}.wav | run-as com.beatz.app sh -c 'cat > /data/data/com.beatz.app/files/stems/${NAME}/${stem}.wav'"
                $ADB -s "$DEVICE" shell "rm /data/local/tmp/${stem}.wav"
            fi
        done
    fi

    # Cleanup
    rm -rf "$SONG_WORK"
    echo "[$NAME] DONE"
}

# Song list
declare -A SONGS
SONGS[Chaiyya_Chaiyya]="https://www.youtube.com/watch?v=AEId3mGnMKo"
SONGS[Kala_Chashma]="https://www.youtube.com/watch?v=k4yXQkG2s1E"
SONGS[London_Thumakda]="https://www.youtube.com/watch?v=udra3Mfw2oo"
SONGS[Senorita_ZNMD]="https://www.youtube.com/watch?v=bdbMivSjrqU"
SONGS[Badtameez_Dil]="https://www.youtube.com/watch?v=II2EO3Nw4Q0"
SONGS[Tujhe_Dekha_Toh]="https://www.youtube.com/watch?v=PbFBp92stAY"
SONGS[Channa_Mereya]="https://www.youtube.com/watch?v=284Ov7ysmfA"
SONGS[Kal_Ho_Naa_Ho]="https://www.youtube.com/watch?v=lWnhI8OmOvM"
SONGS[Tum_Hi_Ho]="https://www.youtube.com/watch?v=Umqb9KENgmk"
SONGS[Kun_Faya_Kun]="https://www.youtube.com/watch?v=T94PHkuydcw"
SONGS[Kabira]="https://www.youtube.com/watch?v=jHNNMj5bNQw"
SONGS[Ilahi]="https://www.youtube.com/watch?v=3wkuqRFXNvI"
SONGS[Khaabon_Ke_Parinday]="https://www.youtube.com/watch?v=M3MNsHM9lCA"
SONGS[Agar_Tum_Saath_Ho]="https://www.youtube.com/watch?v=sK7riqg2mr4"
SONGS[Tere_Bina]="https://www.youtube.com/watch?v=nMfPqeZjc2c"

echo "=== Processing ${#SONGS[@]} songs ==="
echo "Device: ${DEVICE:-none}"
echo ""

TOTAL=${#SONGS[@]}
COUNT=0

for NAME in "${!SONGS[@]}"; do
    COUNT=$((COUNT + 1))
    URL="${SONGS[$NAME]}"

    # Skip if already processed
    if [ -d "$DEST_DIR/$NAME" ] && [ -f "$DEST_DIR/$NAME/vocals.wav" ]; then
        echo "[$COUNT/$TOTAL] $NAME — already done, pushing to phone..."
        if [ -n "$DEVICE" ]; then
            $ADB -s "$DEVICE" shell "run-as com.beatz.app mkdir -p /data/data/com.beatz.app/files/stems/$NAME"
            for stem in vocals drums bass other; do
                if [ -f "$DEST_DIR/$NAME/$stem.wav" ]; then
                    $ADB -s "$DEVICE" push "$DEST_DIR/$NAME/$stem.wav" "/data/local/tmp/${stem}.wav" 2>/dev/null
                    $ADB -s "$DEVICE" shell "cat /data/local/tmp/${stem}.wav | run-as com.beatz.app sh -c 'cat > /data/data/com.beatz.app/files/stems/${NAME}/${stem}.wav'"
                    $ADB -s "$DEVICE" shell "rm /data/local/tmp/${stem}.wav"
                fi
            done
        fi
        continue
    fi

    echo "[$COUNT/$TOTAL] Processing $NAME..."
    process_song "$URL" "$NAME" || echo "[$NAME] FAILED — continuing..."
    echo ""
done

echo "=== All done! ==="
