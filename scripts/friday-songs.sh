#!/bin/bash
# Friday Demo — 15 songs to process
# Run from: /home/iti/git-repos/beatz/scripts/
# Each song takes ~5-10 min (download + demucs + whisper)
#
# Usage: ./friday-songs.sh
# Or run individual lines manually if you prefer one at a time.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Processing 15 songs for Friday singalong demo..."
echo "Each takes ~5-10 min. Total: ~1.5-2.5 hours."
echo ""

# High Energy / Party Starters
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=AEId3mGnMKo" "Chaiyya_Chaiyya"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=k4yXQkG2s1E" "Kala_Chashma"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=udra3Mfw2oo" "London_Thumakda"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=bdbMivSjrqU" "Senorita_ZNMD"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=II2EO3Nw4Q0" "Badtameez_Dil"

# Singalong Classics
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=PbFBp92stAY" "Tujhe_Dekha_Toh"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=284Ov7ysmfA" "Channa_Mereya"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=lWnhI8OmOvM" "Kal_Ho_Naa_Ho"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=Umqb9KENgmk" "Tum_Hi_Ho"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=T94PHkuydcw" "Kun_Faya_Kun"

# Unplugged / Chill
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=jHNNMj5bNQw" "Kabira"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=3wkuqRFXNvI" "Ilahi"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=M3MNsHM9lCA" "Khaabon_Ke_Parinday"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=sK7riqg2mr4" "Agar_Tum_Saath_Ho"
"$SCRIPT_DIR/youtube-to-stems.sh" "https://www.youtube.com/watch?v=nMfPqeZjc2c" "Tere_Bina"

echo ""
echo "Done! Total songs available:"
ls ~/Music/karaoke/htdemucs/ | wc -l
