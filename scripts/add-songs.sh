#!/bin/bash
# Add songs end to end: download, separate, normalise, fetch lyrics, align.
#
# Reads a manifest of  folder_name | youtube search | lyrics title | artist
# (the artist is optional) and works
# through it, skipping any song whose stems already exist so an interrupted run
# can simply be restarted.
#
# Separation uses htdemucs_ft to match the rest of the library — four specialist
# models, roughly 2x realtime, so budget ~10 min for a 5 minute song. Pass
# --fast to use plain htdemucs instead (~2.5 min, slightly muddier stems).
#
# Re-running over songs that already have stems is safe and useful: it looks up
# the video's real title and retries the lyrics for anything still without
# words. Words already on disk are LEFT ALONE -- several songs in this library
# were fixed by pasting lyrics in the player, and a re-run must never overwrite
# those. Pass --refresh-lyrics to deliberately re-fetch them.
#
# Usage: ./scripts/add-songs.sh manifest.txt [--fast] [--refresh-lyrics]

set -uo pipefail

MANIFEST="${1:?usage: add-songs.sh manifest.txt [--fast] [--refresh-lyrics]}"
MODEL=htdemucs_ft
REFRESH=0
for a in "$@"; do
  [ "$a" = "--fast" ] && MODEL=htdemucs
  [ "$a" = "--refresh-lyrics" ] && REFRESH=1
done

VENV=~/demucs-env/bin
SRC=~/Music/karaoke/htdemucs
WORK=~/Music/beatz_pipeline
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$WORK" "$SRC"

total=$(grep -cvE '^\s*(#|$)' "$MANIFEST")
n=0
ok=0; failed=0; skipped=0

# Fourth field is the artist, optional — see the lyrics step below for why it
# must not be glued onto the search string.
while IFS='|' read -r NAME YT LYR ART <&3; do
  case "$NAME" in ''|\#*) continue;; esac
  NAME=$(echo "$NAME" | xargs); YT=$(echo "$YT" | xargs); LYR=$(echo "$LYR" | xargs)
  ART=$(echo "${ART:-}" | xargs)
  # A blank name would make DIR the library root and scatter stems across it.
  if [ -z "$NAME" ] || [ -z "$YT" ]; then
    echo "  SKIP: malformed manifest line (name='$NAME' yt='$YT')"; continue
  fi
  # Force the name to [A-Za-z0-9_]. Three separate things depend on this:
  # prepare-web.sh silently drops any other name from the player's manifest,
  # setup-phone.sh feeds it to a remote shell where spaces split the path, and
  # a name is about to become untrusted input once requests arrive from the
  # web. Runs of rejected characters collapse to one underscore.
  CLEAN=$(printf '%s' "$NAME" | tr -cs 'A-Za-z0-9_' '_' | sed 's/_*$//')
  if [ "$CLEAN" != "$NAME" ]; then
    echo "  name '$NAME' -> '$CLEAN'"
    NAME="$CLEAN"
  fi
  if [ -z "$NAME" ]; then
    echo "  SKIP: name had no usable characters"; continue
  fi
  n=$((n+1))
  DIR="$SRC/$NAME"
  # Per-song, and cleared here: left set, a previous song's video title would
  # drive this one's lyrics search.
  YTTITLE=""; YTID=""

  echo ""
  echo "=========================================================="
  echo "[$n/$total] $NAME"
  echo "=========================================================="

  if [ -f "$DIR/vocals.wav" ]; then
    echo "  stems already exist — skipping separation"
  else
    echo "  [1/4] downloading: $YT"
    rm -f "$WORK/dl.mp3" "$WORK/yt.tsv"
    # Resolve the search to a specific video FIRST, then fetch that video by id.
    # Two calls rather than one because the video's own title is the only
    # correctly-spelled name of the song anywhere in this pipeline — the
    # request was typed from memory — and downloading by id guarantees the
    # title we recorded belongs to the audio we actually got.
    "$VENV/yt-dlp" --js-runtimes node --no-playlist --skip-download \
      --print "%(id)s\t%(title)s" "ytsearch1:$YT" > "$WORK/yt.tsv" 2>/dev/null || true
    YTID=$(head -1 "$WORK/yt.tsv" | cut -f1)
    YTTITLE=$(head -1 "$WORK/yt.tsv" | cut -f2-)
    if [ -z "$YTID" ]; then
      echo "  FAIL: nothing found on YouTube for '$YT'"; failed=$((failed+1)); continue
    fi
    echo "        found: $YTTITLE"
    "$VENV/yt-dlp" --js-runtimes node -x --audio-format mp3 --audio-quality 0 \
      --no-playlist -o "$WORK/dl.mp3" "https://www.youtube.com/watch?v=$YTID" >/dev/null 2>&1
    if [ ! -f "$WORK/dl.mp3" ]; then
      echo "  FAIL: download produced nothing"; failed=$((failed+1)); continue
    fi
    DUR=$("$VENV/python" -c "import subprocess,sys;print(subprocess.run(['ffprobe','-v','quiet','-show_entries','format=duration','-of','csv=p=0','$WORK/dl.mp3'],capture_output=True,text=True).stdout.strip()[:5])" 2>/dev/null)
    echo "        got ${DUR}s of audio"

    echo "  [2/4] separating with $MODEL (this is the slow part)"
    rm -rf "$WORK/sep"
    "$VENV/python" -m demucs -n "$MODEL" --out "$WORK/sep" "$WORK/dl.mp3" >/dev/null 2>&1
    STEM=$(ls -td "$WORK/sep/$MODEL/"*/ 2>/dev/null | head -1)
    if [ -z "$STEM" ]; then
      echo "  FAIL: separation produced nothing"; failed=$((failed+1)); continue
    fi
    mkdir -p "$DIR"
    cp "$STEM"/*.wav "$DIR/"
    "$VENV/python" "$SCRIPT_DIR/normalize-stems.py" "$DIR" >/dev/null 2>&1
    # Kept beside the stems so a later re-run of the lyrics step, or a human
    # wondering what this actually is, does not have to search YouTube again.
    "$VENV/python" -c "import json,sys;json.dump({'ytId':sys.argv[1],'ytTitle':sys.argv[2],'typed':sys.argv[3]},open(sys.argv[4],'w'),ensure_ascii=False,indent=1)" \
      "$YTID" "$YTTITLE" "$NAME" "$DIR/source.json" 2>/dev/null || true
    echo "        stems written + normalised"
  fi

  # Available whether or not we just downloaded: a re-run reads it back.
  if [ -z "${YTTITLE:-}" ] && [ -f "$DIR/source.json" ]; then
    YTTITLE=$("$VENV/python" -c "import json,sys;print(json.load(open(sys.argv[1])).get('ytTitle') or '')" "$DIR/source.json" 2>/dev/null)
  fi
  # Songs separated before this existed have no source.json, and their stems
  # short-circuit the download that would have written one. Look the title up
  # on its own -- it is metadata only, no audio -- so re-running this script
  # over the existing library can fix its lyrics and titles too.
  if [ -z "${YTTITLE:-}" ]; then
    YTTITLE=$("$VENV/yt-dlp" --js-runtimes node --no-playlist --skip-download \
      --print "%(title)s" "ytsearch1:$YT" 2>/dev/null | head -1)
    if [ -n "$YTTITLE" ]; then
      echo "        source: $YTTITLE"
      "$VENV/python" -c "import json,sys;json.dump({'ytTitle':sys.argv[1],'typed':sys.argv[2]},open(sys.argv[3],'w'),ensure_ascii=False,indent=1)" \
        "$YTTITLE" "$NAME" "$DIR/source.json" 2>/dev/null || true
    fi
  fi

  # The lyrics search is the TITLE alone; the artist goes over separately.
  # LRCLIB matches a query near-literally, so "Aao huzoor Asha bhonsle" finds
  # nothing where "Aao huzoor" finds the song — measured across 29 requests,
  # folding the artist in was the single biggest cause of zero hits. The
  # artist then ranks the results, and the separated audio's own length throws
  # out same-name-different-song matches.
  DUR=$("$VENV/python" -c "import subprocess,sys;print(subprocess.run(['ffprobe','-v','quiet','-show_entries','format=duration','-of','csv=p=0',sys.argv[1]],capture_output=True,text=True).stdout.strip() or 0)" "$DIR/vocals.wav" 2>/dev/null)

  # Words already here stay unless asked otherwise. A hand-pasted set is the
  # most valuable thing in the directory and there is no way to get it back.
  EXISTING=0
  if [ -f "$DIR/lyrics.txt" ]; then
    EXISTING=$(grep -cvE '^\s*$' "$DIR/lyrics.txt" 2>/dev/null || echo 0)
  fi
  if [ "$REFRESH" -eq 0 ] && [ "$EXISTING" -ge 8 ]; then
    echo "  [3/4] lyrics: keeping the $EXISTING lines already here"
    ok=$((ok+1)); continue
  fi

  echo "  [3/4] lyrics: $LYR${ART:+  (artist: $ART)}"
  if ! "$VENV/python" "$SCRIPT_DIR/fetch-lyrics-lrclib.py" "$LYR" "$DIR/lyrics.txt" \
        ${YTTITLE:+--yt-title "$YTTITLE"} ${ART:+--artist "$ART"} ${DUR:+--duration "$DUR"}; then
    echo "        no usable lyrics — stems are still fine, words need doing by hand"
    ok=$((ok+1)); continue
  fi

  echo "  [4/4] aligning"
  if "$VENV/python" "$SCRIPT_DIR/align-lyrics.py" "$DIR" --force >/dev/null 2>&1; then
    LINES=$("$VENV/python" -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$DIR/lyrics_timed.json" 2>/dev/null)
    echo "        aligned ${LINES} lines"
    ok=$((ok+1))
  else
    echo "        alignment failed — words present, timing missing"
    ok=$((ok+1))
  fi
done 3< "$MANIFEST"

echo ""
echo "=========================================================="
echo "done: $ok processed, $failed failed, $skipped skipped"
echo "next: ./scripts/prepare-web.sh && ./scripts/deploy-web.sh"
echo "=========================================================="
