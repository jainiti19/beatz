# Beatz — Initial Concept

## Core Idea
An Android app that extracts beats from an existing song and lets the user modify them, with control over instrument, tempo, key, scale, timber, and texture.

## Confirmed Requirements

### Song Input
- **Phase 1:** Pick MP3 from phone storage
- **Later:** Record live, stream from Spotify/YouTube
- **Format:** MP3 to start, more formats later

### Beat Generation — Extract & Modify
- Extract the beat from an existing song, then let user modify it
- Approach: Whichever is easier and costs less (AI/ML or rule-based) — prefer free/open-source
- **Starting Instruments:** Tabla, Guitar, Drums, Flute, Piano (add more later)
- **Layering:** Phase 1 = one instrument at a time; later = multiple layers

### Output & Playback
- Export as MP3
- Real-time playback while adjusting parameters
- Phase 1: Sliders and controls; later: visual beat editor/sequencer

### Technical Stack
- Language: **Kotlin**
- UI: **Jetpack Compose** (Material 3)
- Audio Engine: **MWEngine** (C++ engine with Kotlin API)
- Audio Analysis: **TarsosDSP** (Android fork)
- MP3 Export: **TAndroidLame** (LAME wrapper)
- Architecture: **MVVM** with Hilt DI
- All free/open-source

### Scope
- Phase 1: Personal MVP
- Later: Play Store release

## Key Libraries
| Library | Purpose | Link |
|---------|---------|------|
| MWEngine | Audio engine, sequencing, sample playback | github.com/igorski/MWEngine |
| TarsosDSPAndroid | BPM and pitch detection | github.com/AnandaAp/TarsosDSPAndroid |
| TAndroidLame | MP3 encoding/export | github.com/naman14/TAndroidLame |
| FluidSynth | SoundFont synthesis (Phase 4+) | fluidsynth.org |
