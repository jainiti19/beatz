#!/bin/bash
# Prepare stems for web deployment
# Creates web/stems/ with songs.json manifest and symlinks/copies of stem files
# Usage: ./scripts/prepare-web.sh [max_songs]

SRC=~/Music/karaoke/htdemucs
WEB_STEMS=web/stems
MAX_SONGS=${1:-10}  # Default 10 songs for testing

echo "Preparing web stems (max $MAX_SONGS songs)..."
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

    # Create song dir and symlink stems
    mkdir -p "$WEB_STEMS/$NAME"
    for stem in vocals drums bass other; do
        if [ -f "$dir/$stem.wav" ]; then
            ln -sf "$(realpath "$dir/$stem.wav")" "$WEB_STEMS/$NAME/$stem.wav"
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
    echo "  [$COUNT] $DISPLAY"
done

echo "" >> "$WEB_STEMS/songs.json"
echo "]" >> "$WEB_STEMS/songs.json"

echo ""
echo "Prepared $COUNT songs in $WEB_STEMS/"
echo "To test locally: cd web && python3 -m http.server 8080"
echo "Then open: http://localhost:8080"
