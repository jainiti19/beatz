#!/bin/bash
# Prepare stems for web deployment
# Converts WAV stems to MP3 for fast loading, generates songs.json manifest
# Usage: ./scripts/prepare-web.sh [max_songs]

SRC=~/Music/karaoke/htdemucs
WEB_STEMS=web/stems
# A safety rail against a runaway loop, not a library size. It used to default
# to 100 and the library reached exactly 100 — Zindagi Ek Safar was fully
# processed and silently absent from the player, because watch-requests.py
# calls this with no argument. Raise it before the VPS disk becomes the real
# limit: ~22MB a song against 20GB free is roughly 900 songs.
MAX_SONGS=${1:-1000}
BITRATE=192k  # Good quality, small files

echo "Preparing web stems as MP3 (${BITRATE}, max $MAX_SONGS songs)..."
mkdir -p "$WEB_STEMS"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
META="$REPO_DIR/data/songs-meta.json"
HIDDEN=$(python3 -c "
import json,sys
try: m=json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
for k,v in m.items():
    if not k.startswith('_') and isinstance(v,dict) and v.get('hide'): print(k)
" "$META" 2>/dev/null)

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

    # Skip anything marked hide in data/songs-meta.json (duplicates). Done here
    # rather than after the loop so a duplicate costs no MP3 encode and no disk
    # on the VPS.
    echo "$HIDDEN" | grep -qxF "$NAME" && continue

    COUNT=$((COUNT + 1))
    if [ $COUNT -gt $MAX_SONGS ]; then
        echo "  STOPPING at $MAX_SONGS songs — the rest are on disk but will not"
        echo "  be published. Raise MAX_SONGS or pass a higher limit."
        break
    fi

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

    # Copy forced-aligned timings — without this the player falls back to
    # spreading lines evenly across the song, which never matches the singing.
    if [ -f "$dir/lyrics_timed.json" ]; then
        cp "$dir/lyrics_timed.json" "$WEB_STEMS/$NAME/lyrics_timed.json"
    fi

    if [ "$FIRST" = true ]; then
        FIRST=false
    else
        echo "," >> "$WEB_STEMS/songs.json"
    fi
    # rev = newest mp3 mtime. The player holds audio in the Cache API now, and
    # this loop re-encodes to the SAME filename when a wav is newer -- which is
    # why the Caddy header deliberately stops short of `immutable`. Without a
    # rev in the URL a held copy would survive a reprocess forever, invisibly.
    REV=$(stat -c %Y "$WEB_STEMS/$NAME"/*.mp3 2>/dev/null | sort -n | tail -1)
    echo "  {\"name\": \"$DISPLAY\", \"dir\": \"$NAME\", \"rev\": ${REV:-0}}" >> "$WEB_STEMS/songs.json"

    # Show size
    SIZE=$(du -sh "$WEB_STEMS/$NAME" 2>/dev/null | cut -f1)
    echo "  [$COUNT] $DISPLAY ($SIZE)"
done

echo "" >> "$WEB_STEMS/songs.json"
echo "]" >> "$WEB_STEMS/songs.json"

# Cleanup old WAV symlinks
find "$WEB_STEMS" -name "*.wav" -type l -delete 2>/dev/null

# Grade the lyrics and fold the verdict into songs.json. Without this the
# player cannot mark a song whose words are wrong, and the only way to find
# out is to start singing it.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/check-lyrics-quality.py" "$WEB_STEMS"

# Real titles, films and singers. Must run AFTER check-lyrics-quality.py so the
# verdict it writes survives; both rewrite songs.json in place.
python3 "$SCRIPT_DIR/apply-song-meta.py" "$WEB_STEMS" --meta "$META"

TOTAL=$(du -sh "$WEB_STEMS" 2>/dev/null | cut -f1)
echo ""
echo "Prepared $COUNT songs in $WEB_STEMS/ (total: $TOTAL)"
echo "To test locally: cd web && python3 -m http.server 8080"
