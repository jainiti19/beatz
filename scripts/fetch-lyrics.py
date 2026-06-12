#!/usr/bin/env python3
"""
Fetch lyrics from Genius API for a given song name.
Usage: python3 fetch-lyrics.py "Tum Hi Ho" [output_file]
"""

import sys
import re
import json
import urllib.request
import urllib.parse
from html.parser import HTMLParser

GENIUS_TOKEN = "fc189dBOSoAu4pTpOXkPUxnJYq6PobcGFn0j3wJjla-Cosqt6OZRyfapkMGlHyIU"


class LyricsParser(HTMLParser):
    """Extract text from Genius lyrics HTML."""
    def __init__(self):
        super().__init__()
        self.in_lyrics = False
        self.lyrics = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class", "")
        data_attr = attrs_dict.get("data-lyrics-container", "")
        if data_attr == "true" or "Lyrics__Container" in class_name:
            self.in_lyrics = True
            self.depth = 0
        if self.in_lyrics:
            self.depth += 1
            if tag == "br":
                self.lyrics.append("\n")

    def handle_endtag(self, tag):
        if self.in_lyrics:
            self.depth -= 1
            if self.depth <= 0:
                self.in_lyrics = False

    def handle_data(self, data):
        if self.in_lyrics:
            self.lyrics.append(data)


def clean_query(query):
    """Clean up a song folder name into a proper search query."""
    # Remove common YouTube title junk
    junk = [
        r'Full Song.*', r'Full Video.*', r'Official.*', r'Lyric(al|s)?.*Video',
        r'HD.*', r'HQ.*', r'Audio.*', r'\(From.*?\)', r'Feat\..*',
        r'with.*audio.*', r'Song With Lyrics.*', r'Lyrical.*',
        r'\d{4}', r'Bollywood.*', r'Latest.*', r'New.*Song',
        r'Male Version.*', r'Female Version.*', r'Tribute.*',
    ]
    cleaned = query
    for pattern in junk:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    # Remove extra spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # If too short after cleaning, use original
    if len(cleaned) < 3:
        cleaned = query
    return cleaned


def search_genius(query):
    """Search Genius for a song, return the URL of the best match."""
    cleaned = clean_query(query)

    # Search with multiple strategies
    queries_to_try = [
        cleaned,                          # Original cleaned
        cleaned + " lyrics",              # With lyrics hint
        cleaned + " Romanized",           # Direct romanized search
    ]

    best_url = None
    best_title = None

    for search_q in queries_to_try:
        encoded = urllib.parse.quote(search_q)
        url = f"https://api.genius.com/search?q={encoded}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {GENIUS_TOKEN}"
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except:
            continue

        hits = data.get("response", {}).get("hits", [])
        if not hits:
            continue

        # Prefer Romanized results (better for sing-along)
        for hit in hits[:5]:
            title = hit["result"]["full_title"].lower()
            if "romanized" in title:
                return hit["result"]["url"], hit["result"]["full_title"]

        # Save first result as fallback
        if best_url is None:
            best_url = hits[0]["result"]["url"]
            best_title = hits[0]["result"]["full_title"]

    return best_url, best_title


def fetch_lyrics_from_url(url):
    """Scrape lyrics from a Genius song page."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    parser = LyricsParser()
    parser.feed(html)

    lyrics = "".join(parser.lyrics).strip()

    # Clean up
    lyrics = re.sub(r'\[.*?\]', '', lyrics)  # Remove [Verse], [Chorus] etc.
    lyrics = re.sub(r'\d+\s*Contributor.*?Lyrics\n?', '', lyrics)  # Remove header
    lyrics = re.sub(r'Translations.*?Lyrics\n?', '', lyrics)  # Remove translations header
    lyrics = re.sub(r'You might also like.*', '', lyrics)  # Remove suggestions
    lyrics = re.sub(r'See .*? LiveGet tickets.*?\n?', '', lyrics)  # Remove concert ads
    lyrics = re.sub(r'Embed$', '', lyrics, flags=re.MULTILINE)  # Remove Embed button text
    lyrics = re.sub(r'\d+Embed$', '', lyrics, flags=re.MULTILINE)
    lyrics = re.sub(r'Subscribe.*?icon\.', '', lyrics)  # Remove subscribe prompts
    lyrics = re.sub(r'\n{3,}', '\n\n', lyrics)  # Max 2 newlines
    lyrics = lyrics.strip()

    return lyrics


def fetch_lyrics(song_name):
    """Search and fetch lyrics for a song."""
    url, title = search_genius(song_name)
    if not url:
        return None, None

    lyrics = fetch_lyrics_from_url(url)
    return lyrics, title


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 fetch-lyrics.py 'song name' [output_file]")
        sys.exit(1)

    song = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Searching: {song}")
    lyrics, title = fetch_lyrics(song)

    if lyrics:
        print(f"Found: {title}")
        print(f"Lyrics length: {len(lyrics)} chars")
        if output_file:
            with open(output_file, "w") as f:
                f.write(lyrics)
            print(f"Saved to: {output_file}")
        else:
            print("---")
            print(lyrics[:500])
    else:
        print("No lyrics found")
