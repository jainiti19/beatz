#!/usr/bin/env python3
"""Cases the lyrics matcher has got wrong, so it cannot get them wrong again.

Every entry here is a real failure that reached the library, not an invented
one. No network: each case is a hit LRCLIB actually returned, replayed through
belongs_to_audio(), which is the gate that decides whether words get written.

Run: python3 scripts/test-lyrics-matcher.py
"""
import importlib.util, os, sys

_spec = importlib.util.spec_from_file_location(
    "fl", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch-lyrics-lrclib.py"))
fl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fl)

# label, hit trackName, hit artistName, YouTube title, what was typed, keep?
CASES = [
    # --- must be REJECTED -------------------------------------------------
    ("rafi: artist word borrowed",
     'Wada Kar Le Sajna (From "Haath Ki Safai") (feat. Mohammed Rafi)', "Lata Mangeshkar",
     "Kya Hua Tera Wada-Lyrical | क्या हुआ तेरा वादा | Hum Kisise kum nahi | "
     "Mohammed Rafi | Rishi Kapoor",
     "Kya hua tera wada", False),
    # Rafi sang the song we asked for, so his name is in the upload title, so
    # ANY Rafi track shared a word with it. Published 2 Sep, graded "check".
    ("agneepath: film word borrowed",
     "Agneepath (Ek Awaaz)", "Bintu Pabra feat. Kp Kundu",
     "Ajay-Atul - Abhi Mujh Mein Kahin Best Lyric|Agneepath|Priyanka Chopra,"
     "Hrithik|Sonu Nigam",
     "Abhi mujh mein kahin", False),
    # The film name is in the title, and an unrelated single is named after the
    # film. Published 2 Sep and graded "good", so nothing flagged it.
    ("bruno mars: right artist, wrong song",
     "Natalie", "Bruno Mars", "Bruno Mars - Just The Way You Are",
     "Just the way you are", False),

    # --- must be KEPT -----------------------------------------------------
    ("transliteration: doubled vowel",
     "Qaafirana", "Arijit Singh",
     "Qaafirana Full Song | Kedarnath | Sushant Rajput | Sara Ali Khan",
     "Qafirana", True),
    # An exact word test rejected this CORRECT match: LRCLIB spells it with
    # two a's and the uploader with one. It is why _same_word is fuzzy.
    ("transliteration: k for q",
     "Dama Dam Mast Qalandar", "Runa Laila",
     '"Dama Dam Mast Qalandar" most popular Qawwali, By: Runa Laila (With Lyrics)',
     "Damadam mast kalandar", True),
    ("misspelt request",
     "Tu Kisi Rail Si", "Ankit Tiwari", "Tu Kisi Rail Si | Masaan | Indian Ocean",
     "Tu kisi raii si", True),
    ("uploader's quote marks name the song",
     'Mujhe Raat Din Bas (From "Sangharsh")', "Sonu Nigam",
     '"Mujhe Raat Din Bas" [Full Song] | Sangharsh | Sonu Nigam',
     "Mujhe raat din", True),
    ("LRCLIB spells it longer",
     "Main Duniya Bhula Doonga", "Anuradha Paudwal",
     "Main Duniya Bhula Dunga | Aashiqui | Kumar Sanu", "Main Duniya Bhula Dunga", True),
    ("no video title: nothing to judge against",
     "Anything At All", "Someone", None, "whatever", True),
]

if __name__ == "__main__":
    bad = 0
    for label, track, artist, yt, typed, want in CASES:
        got = fl.belongs_to_audio({"trackName": track, "artistName": artist}, yt, typed)
        if got == want:
            print(f"  ok    {label}")
        else:
            bad += 1
            print(f"  FAIL  {label}: keep={got}, expected {want}")
    print(f"\n{len(CASES) - bad}/{len(CASES)} passed")
    sys.exit(1 if bad else 0)
