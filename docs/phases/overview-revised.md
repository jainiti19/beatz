# Beatz — Revised Build Plan

**Date:** 2026-06-02
**Core Use Case:** Generate acoustic jamming/backing tracks for sing-along sessions
**Think:** Open mic / unplugged session — guitarist + dholak player accompanying a singer

---

## What's Already Built

| Phase | Status | What |
|-------|--------|------|
| 0 | DONE | Environment setup (Android Studio, SDK, emulator) |
| 1 | DONE | MVP (file picker, decode, BPM/key detect, 5 instruments, playback, WAV export) |
| 2a-b | DONE | Multi-layer engine + Layer UI (volume, mute, solo) |
| 2c-d | DONE | Scale-aware melody + Scale/Raga selector (6 Western + 10 Indian ragas) |
| 2e | DONE | Raga system (10 ragas, direction-aware snapping) |
| — | DONE | Demucs vocal separation installed (Python, runs on CPU ~2 min/song) |

**Total: 29 Kotlin source files, builds and runs on emulator**

---

## Revised Phases (Jamming Track Focus)

### Phase 3: Chord Detection Engine
**Goal:** Extract the actual chord progression from any song, timed to the music.
**This is the foundation — everything else depends on knowing the chords.**

| # | Task | Description | Est. |
|---|------|-------------|------|
| 3a | Chromagram analysis | FFT → 12-bin chroma vector per time window | 4h |
| 3b | Chord matching | Match chroma vectors to chord templates (maj, min, 7th, dim) | 4h |
| 3c | Chord timeline | List of (chord, startTime, endTime) for the whole song | 3h |
| 3d | Display chords | Show detected chords on Analysis screen | 2h |
| 3e | Store in AnalysisResult | Pass chord timeline to Beat Editor | 1h |

**Output:** "Am (0-4s) → G (4-8s) → F (8-12s) → E (12-16s) → ..."
**Effort:** 12-14 hours

---

### Phase 4: Acoustic Instrument Sounds
**Goal:** Sound like a real unplugged jam, not synthetic beeps.

| # | Task | Description | Est. |
|---|------|-------------|------|
| 4a | Acoustic guitar strumming | Karplus-Strong per string, strum patterns (down/up), chord voicings | 8h |
| 4b | Cajon sounds | Synthetic bass (tun), slap (tak), ghost notes | 3h |
| 4c | Dholak sounds | Bass (ge), treble (na), combined (dhin) | 3h |
| 4d | Harmonium sustained pad | Additive synth with tremolo, sustained envelope, chord support | 4h |
| 4e | Instrument quality test | Compare against real recordings, tune parameters | 3h |

**Effort:** 18-21 hours

---

### Phase 5: Jamming Track Generator
**Goal:** Given chords + BPM + key → generate a full-length acoustic backing track that follows the song structure.

| # | Task | Description | Est. |
|---|------|-------------|------|
| 5a | Chord-driven pattern engine | Guitar strums the detected chord at each change | 6h |
| 5b | Strum pattern library | 4-6 common patterns (ballad, upbeat, folk, Bollywood) | 4h |
| 5c | Cajon/Dholak auto-rhythm | Rhythm pattern that matches the feel (tempo-adaptive) | 4h |
| 5d | Harmonium pad layer | Sustained chord pads following progression | 3h |
| 5e | Full-song rendering | Render backing track for entire song duration (not just 8 bars) | 4h |
| 5f | Song structure detection | Detect verse/chorus sections for dynamic arrangement | 6h |

**Effort:** 24-27 hours

---

### Phase 6: Hybrid Mode (Demucs + Acoustic)
**Goal:** Best of both worlds — use AI-separated bass/harmony from original + our acoustic instruments.

| # | Task | Description | Est. |
|---|------|-------------|------|
| 6a | Demucs integration in app | Run separation (or import pre-separated stems) | 6h |
| 6b | Stem mixer | Mix original bass + our guitar + our percussion | 4h |
| 6c | Balance controls | Volume per stem (original bass, guitar, percussion, harmonium) | 3h |
| 6d | One-tap "Jamming Mode" | Pick song → auto-generate full backing track | 4h |

**Effort:** 15-17 hours

---

### Phase 7: Sing-Along UI
**Goal:** Beautiful sing-along experience with lyrics, chords, and playback.

| # | Task | Description | Est. |
|---|------|-------------|------|
| 7a | Lyrics display | Show scrolling lyrics synced to playback (manual input initially) | 6h |
| 7b | Chord overlay | Show guitar chord names above lyrics at correct positions | 3h |
| 7c | Tempo control | Speed up/slow down for practice | 2h |
| 7d | Loop sections | Select and loop verse/chorus for practice | 4h |
| 7e | Key transpose | Shift all chords up/down to match singer's range | 3h |

**Effort:** 16-18 hours

---

### Phase 8: Play Store & Polish
**Goal:** Production-ready app.

| # | Task | Description | Est. |
|---|------|-------------|------|
| 8a | UI polish | Icon, splash screen, dark mode, onboarding | 8h |
| 8b | Physical device testing | Test on real Android phone | 4h |
| 8c | Performance optimization | Profile, optimize chord detection speed | 4h |
| 8d | Error handling | Edge cases, crash recovery | 4h |
| 8e | Play Store listing | Developer account, privacy policy, screenshots | 6h |

**Effort:** 24-26 hours

---

## Summary

| Phase | Name | Status | Est. Hours |
|-------|------|--------|------------|
| 0 | Environment Setup | DONE | — |
| 1 | MVP | DONE | — |
| 2 | Multi-Layer + Scales + Ragas | DONE | — |
| **3** | **Chord Detection Engine** | **NEXT** | **12-14h** |
| 4 | Acoustic Instrument Sounds | — | 18-21h |
| 5 | Jamming Track Generator | — | 24-27h |
| 6 | Hybrid Mode (Demucs + Acoustic) | — | 15-17h |
| 7 | Sing-Along UI | — | 16-18h |
| 8 | Play Store & Polish | — | 24-26h |

**Remaining effort: ~110-125 hours**

---

## How a Jamming Track Will Work (End State)

```
User picks "Tauba Tauba" MP3
        ↓
App analyzes: BPM=96, Key=C minor
Detects chords: Cm → G → A♭ → B♭ → Cm → ... (timed to song)
        ↓
User taps "Generate Jamming Track"
        ↓
App generates full-length backing track:
  - Acoustic guitar strumming Cm → G → A♭ → B♭ at 96 BPM
  - Dholak playing keherwa pattern
  - Harmonium pad holding each chord
  - (Optional) Original bass from Demucs
        ↓
User plays it and sings Tauba Tauba over it
Like having a live band backing them up
```
