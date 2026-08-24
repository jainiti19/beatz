#!/bin/bash
# Kishore Kumar Playlist — 20 most sung songs
# Usage: ./scripts/kishore-kumar-songs.sh
# Each song takes ~5-10 min (download + demucs + whisper)
# Total: ~2-3 hours

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Processing 20 Kishore Kumar songs..."
echo "Each takes ~5-10 min. Total: ~2-3 hours."
echo ""

# Evergreen Classics
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Pal Pal Dil Ke Paas Kishore Kumar Blackmail" "Pal_Pal_Dil_Ke_Paas"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Mere Sapno Ki Rani Kishore Kumar Aradhana" "Mere_Sapno_Ki_Rani"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Roop Tera Mastana Kishore Kumar Aradhana" "Roop_Tera_Mastana"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Yeh Sham Mastani Kishore Kumar Kati Patang" "Yeh_Sham_Mastani"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Kuch Toh Log Kahenge Kishore Kumar Amar Prem" "Kuch_Toh_Log_Kahenge"

# Romantic Hits
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Rim Jhim Gire Sawan Kishore Kumar Manzil" "Rim_Jhim_Gire_Sawan"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:O Mere Dil Ke Chain Kishore Kumar" "O_Mere_Dil_Ke_Chain"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Ye Jo Mohabbat Hai Kishore Kumar Kati Patang" "Ye_Jo_Mohabbat_Hai"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Chingari Koi Bhadke Kishore Kumar Amar Prem" "Chingari_Koi_Bhadke"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Phoolon Ke Rang Se Kishore Kumar Prem Pujari" "Phoolon_Ke_Rang_Se"

# Fun & Peppy
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Ek Ladki Bheegi Bhaagi Si Kishore Kumar" "Ek_Ladki_Bheegi_Bhaagi_Si"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Mere Naina Sawan Bhadon Kishore Kumar" "Mere_Naina_Sawan_Bhadon"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Zindagi Ek Safar Hai Suhana Kishore Kumar" "Zindagi_Ek_Safar"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Yeh Jeevan Hai Kishore Kumar Piya Ka Ghar" "Yeh_Jeevan_Hai"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Aa Chal Ke Tujhe Kishore Kumar" "Aa_Chal_Ke_Tujhe"

# Soulful Melodies
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Chalte Chalte Mere Yeh Geet Kishore Kumar" "Chalte_Chalte"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Dil Kya Kare Jab Kisi Se Kishore Kumar Julie" "Dil_Kya_Kare"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Hume Tumse Pyar Kitna Kishore Kumar Kudrat" "Hume_Tumse_Pyar_Kitna"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Sagar Kinare Dil Ye Pukare Kishore Kumar" "Sagar_Kinare"
"$SCRIPT_DIR/youtube-to-stems.sh" "search:Agar Tum Na Hote Kishore Kumar" "Agar_Tum_Na_Hote"

echo ""
echo "Done! Kishore Kumar songs processed:"
ls ~/Music/karaoke/htdemucs/ | grep -E "Pal_Pal|Mere_Sapno|Roop_Tera|Yeh_Sham|Kuch_Toh|Rim_Jhim|O_Mere_Dil|Ye_Jo|Chingari|Phoolon|Ek_Ladki|Mere_Naina|Zindagi_Ek|Yeh_Jeevan|Aa_Chal|Chalte_Chalte|Dil_Kya|Hume_Tumse|Sagar_Kinare|Agar_Tum_Na" | wc -l
echo "out of 20"
