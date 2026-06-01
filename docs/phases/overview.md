# Beatz — Implementation Phases

## Status Overview

| Phase | Name | Status | Est. Effort |
|-------|------|--------|-------------|
| 0 | Environment Setup | COMPLETE | 4-6 hours |
| 1 | MVP | COMPLETE | 30-40 hours |
| 2 | Multi-Instrument & Advanced Controls | NOT STARTED | 20-30 hours |
| 3 | Live Recording & Visual Editor | NOT STARTED | 17-23 hours |
| 4 | Streaming Input & Instrument Library | NOT STARTED | 18-23 hours |
| 5 | Play Store Prep & Polish | NOT STARTED | 18-24 hours |

**Total estimated: ~2-3 months part-time**

---

## Phase 0: Environment Setup
**Goal:** Android Studio installed, emulator running, "Hello Beatz" on screen, git repo set up.

### Tasks
- [ ] Install Android Studio
- [ ] Configure SDK (API 34, Build-Tools, Emulator)
- [ ] Create Pixel 7 emulator (API 34)
- [ ] Create project ("Empty Compose Activity", package: `com.beatz.app`, Kotlin, min SDK 26)
- [ ] Run on emulator — see "Hello Beatz"
- [ ] Set up `.gitignore` and initial commit
- [ ] Create package folder structure

---

## Phase 1: MVP
**Goal:** Pick an MP3 → detect tempo/key → generate drum pattern → adjust with sliders → real-time playback → export as MP3.

### Sub-tasks
- [ ] **1a. File Picker** — "Pick a Song" button, system file picker, copy to internal storage
- [ ] **1b. MP3 Decoding** — MediaExtractor + MediaCodec → PCM
- [ ] **1c. Tempo Detection** — TarsosDSP BeatRoot → BPM
- [ ] **1d. Key Detection** — TarsosDSP PitchProcessor → estimated key
- [ ] **1e. Analysis Screen** — progress indicator, display BPM/key, "Generate Beat" button
- [ ] **1f. Beat Pattern Generation** — kick/snare/hi-hat pattern, parameterizable by BPM
- [ ] **1g. Audio Engine** — MWEngine setup, load samples, sequencer, play/pause/stop
- [ ] **1h. Beat Editor Screen** — BPM slider, instrument selector, transport buttons
- [ ] **1i. Real-time Playback** — live BPM changes, beat position indicator
- [ ] **1j. MP3 Export** — offline render → LAME encode → save to Music dir → share
- [ ] **1k. Navigation & Polish** — Compose Navigation, error handling, loading states

---

## Phase 2: Multi-Instrument & Advanced Controls
**Goal:** Layer multiple instruments, add scale/timber/texture controls, key transposition.

### Sub-tasks
- [ ] **2a.** Multi-layer architecture (multiple MWEngine channels)
- [ ] **2b.** Layer UI (list of layers, volume sliders, mute/solo)
- [ ] **2c.** Melodic pattern generation (arpeggios, chord tones respecting key/scale)
- [ ] **2d.** Scale selector (Major, Minor, Pentatonic, Blues, Harmonic Minor)
- [ ] **2e.** Timber control (low-pass/high-pass filter per layer)
- [ ] **2f.** Texture control (density slider + reverb slider)
- [ ] **2g.** Key transposition (+/- semitones)
- [ ] **2h.** Testing & polish

---

## Phase 3: Live Recording & Visual Editor
**Goal:** Microphone recording input, visual beat grid/sequencer, waveform display.

### Sub-tasks
- [ ] **3a.** Microphone recording (AudioRecord API → WAV → analysis pipeline)
- [ ] **3b.** Beat grid sequencer UI (Compose Canvas, tappable cells)
- [ ] **3c.** Playback position indicator (moving cursor on grid)
- [ ] **3d.** Waveform display with beat markers
- [ ] **3e.** Variable pattern length (1, 2, 4, 8 bars)

---

## Phase 4: Streaming Input & Instrument Library
**Goal:** Spotify/YouTube input (with legal considerations), expanded instruments, genre presets.

### Sub-tasks
- [ ] **4a.** Legal review of streaming extraction
- [ ] **4b.** Spotify integration (SDK, auth, playback + analysis)
- [ ] **4c.** YouTube integration (player + audio capture)
- [ ] **4d.** Expanded instrument library (20+ instruments, downloadable packs)
- [ ] **4e.** Genre presets (Hip-hop, EDM, Rock, Bollywood, Jazz)

---

## Phase 5: Play Store Prep & Polish
**Goal:** Production-ready app on Google Play Store.

### Sub-tasks
- [ ] **5a.** UI polish (icon, splash screen, theming, dark mode, onboarding)
- [ ] **5b.** Physical device testing
- [ ] **5c.** Performance optimization (profiling, Baseline Profiles, LeakCanary)
- [ ] **5d.** Error handling & edge cases
- [ ] **5e.** Play Store listing (developer account, privacy policy, screenshots)
- [ ] **5f.** Beta testing (internal → closed → open → production)
