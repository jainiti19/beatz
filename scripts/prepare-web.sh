#!/bin/bash
# Prepare stems for web deployment
# Converts WAV stems to MP3 for fast loading, generates songs.json manifest
# Usage: ./scripts/prepare-web.sh [max_songs]

SRC=~/Music/karaoke/htdemucs
WEB_STEMS=web/stems
MAX_SONGS=${1:-100}
BITRATE=192k  # Good quality, small files

echo "Preparing web stems as MP3 (${BITRATE}, max $MAX_SONGS songs)..."
mkdir -p "$WEB_STEMS"

# Build songs.json
echo "[" > "$WEB_STEMS/songs.json"
COUNT=0
FIRST=true

for dir in "$SRC"/*/; do
    NAME=$(basename "$dir")

    # Skip if missing stems
    [ -f "$dir/vocals.wav" ] && [ -f "$dir/drums.wav" ] || continue

    # Skip names with special chars for web compatibility
    echo "$NAME" | grep -qE '[^a-zA-Z0-9_]' && continue

    COUNT=$((COUNT + 1))
    [ $COUNT -gt $MAX_SONGS ] && break

    DISPLAY=$(echo "$NAME" | sed 's/_/ /g')

    mkdir -p "$WEB_STEMS/$NAME"

    # Convert WAV to MP3
    for stem in vocals drums bass other; do
        if [ -f "$dir/$stem.wav" ]; then
            MP3="$WEB_STEMS/$NAME/$stem.mp3"
            if [ ! -f "$MP3" ] || [ "$dir/$stem.wav" -nt "$MP3" ]; then
                ffmpeg -y -i "$dir/$stem.wav" -b:a $BITRATE -q:a 2 "$MP3" 2>/dev/null
            fi
        fi
    done

    # Copy lyrics if available
    if [ -f "$dir/lyrics.txt" ]; then
        cp "$dir/lyrics.txt" "$WEB_STEMS/$NAME/lyrics.txt"
    fi

    if [ "$FIRST" = true ]; then
        FIRST=false
    else
        echo "," >> "$WEB_STEMS/songs.json"
    fi
    echo "  {\"name\": \"$DISPLAY\", \"dir\": \"$NAME\"}" >> "$WEB_STEMS/songs.json"

    # Show size
    SIZE=$(du -sh "$WEB_STEMS/$NAME" 2>/dev/null | cut -f1)
    echo "  [$COUNT] $DISPLAY ($SIZE)"
done

echo "" >> "$WEB_STEMS/songs.json"
echo "]" >> "$WEB_STEMS/songs.json"

# Cleanup old WAV symlinks
find "$WEB_STEMS" -name "*.wav" -type l -delete 2>/dev/null

TOTAL=$(du -sh "$WEB_STEMS" 2>/dev/null | cut -f1)
echo ""
echo "Prepared $COUNT songs in $WEB_STEMS/ (total: $TOTAL)"
echo "To test locally: cd web && python3 -m http.server 8080"
