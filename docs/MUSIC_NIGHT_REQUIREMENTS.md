# Beatz — Music Night Requirements (Handoff from Planning Session)

## Date: Jun 15, 2026

## Context
Karan (lead singer) tested Beatz on Jun 14. Loved it. First music night event planned for September 2026, 30-35 people at an Indian restaurant. Beatz is the backing track engine — no live musicians.

---

## What Works Today
- Stem separation (Demucs) — vocals/drums/bass/other
- Jamming Mode UI — per-stem volume sliders, presets (Karaoke/Unplugged/Jamming)
- Lyrics display (Whisper transcription)
- 25+ Bollywood songs already processed

## What Needs to Be Built for September

### Must Have

| Feature | Description | Notes |
|---------|-------------|-------|
| **Pre-loaded song library** | Karan will prepare a list of 30-40 songs. All must be pre-processed (stems + lyrics) and ready for instant playback. No processing delay on the night. | Karan to share list. Process via youtube-to-stems.sh |
| **Audio output quality** | Output must sound good through PA speakers, not just headphones/laptop speakers. Test on actual PA system. | May need higher quality WAV output, volume normalization across songs |
| **Lyrics projection web page** | A web page (e.g. beatz.app/live or localhost) that displays lyrics for the current song. Projected on a screen/TV behind the singer. Controlled from laptop. Auto-scroll or manual advance. | Build as a simple Next.js/HTML page. Large font, dark background, readable from distance. |
| **Song switching speed** | Must be able to switch between songs instantly. No loading delays. Crowd energy dies if you wait 30 seconds between songs. | Pre-load all stems in memory or have instant file access |

### Nice to Have

| Feature | Description | Notes |
|---------|-------------|-------|
| **WhatsApp lyrics sharing** | Send lyrics of current/next song to participants via WhatsApp so they can follow on their phones | Could use existing Twilio setup from CashKitty |
| **Song queue / setlist manager** | UI to arrange song order, see what's coming next, drag to reorder | Helps Karan and Iti manage the flow during the event |
| **Participant song requests** | Simple web form where attendees can request a song from the pre-loaded list | Could be a simple page: beatz.app/request |
| **Key/pitch adjustment** | Shift pitch up/down to match singer's range | Karan may need songs in different keys |

### Stretch (not for September)

| Feature | Description |
|---------|-------------|
| Voice message processing | Accept voice notes as song requests |
| Live mixing controls | Bass boost, reverb on mic, etc. |
| Recording | Record the session for sharing later |

---

## Technical Notes

### Lyrics Web Page — Spec
- Dark background, white/yellow text
- Large font (readable from 5+ meters on projected screen)
- Shows: song title, artist, lyrics
- Auto-scroll synced to song playback OR manual scroll/advance
- Controlled from laptop (same machine running Beatz)
- Must work in browser (Chrome) — no app install on venue TV needed
- Simple URL: localhost:3000/live or similar

### Audio Quality Checklist
- [ ] Test Beatz output through JBL PartyBox or similar PA speaker
- [ ] Check for clipping, distortion at volume
- [ ] Normalize volume levels across all 30-40 songs (some are louder than others)
- [ ] Test transition between songs — any clicks/pops?
- [ ] Ensure Karaoke preset (vocals removed) sounds clean, not hollow

### Song Processing Checklist
- [ ] Karan shares song list
- [ ] Process all songs through youtube-to-stems.sh
- [ ] Verify each song: stems sound good, lyrics are accurate
- [ ] Fix any lyrics errors manually
- [ ] Organize in consistent folder structure

---

## Timeline

| When | What |
|------|------|
| Jun-Jul | Karan shares song list. Process all songs. Build lyrics web page. |
| Jul-Aug | Test full setup: laptop + PA + mic + screen. Do 1-2 dry runs with Karan. |
| Aug | Fix issues from dry run. Polish UI. |
| Sep | Event |

---

## Key Principle
**Everything must be pre-loaded and instant on the night. Zero waiting. Zero processing. Zero fumbling.** The tech should be invisible — attendees should feel like they're at a live music session, not watching someone operate software.
