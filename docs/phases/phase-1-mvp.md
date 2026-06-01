# Phase 1: MVP

**Status:** COMPLETE (builds successfully)
**Date Completed:** 2026-03-21
**APK Size:** 9.5MB

---

## What Was Built

### Architecture (Simplified from Plan)
Instead of MWEngine (requires native build from source), we used **pure Kotlin** with Android's built-in APIs:
- **AudioTrack** for low-latency playback (no native code needed)
- **MediaExtractor + MediaCodec** for MP3 decoding (built-in)
- **Custom FFT + energy-based onset detection** for BPM/key analysis (no TarsosDSP)
- **MediaCodec AAC encoder** for export (built-in, outputs M4A)
- **Synthetic sample generation** for instrument sounds (placeholder, replace with real WAVs later)

### Files Created (24 Kotlin files)

**Data Models (4 files):**
- `data/model/Instrument.kt` — 5 instruments: Drums, Tabla, Guitar, Piano, Flute
- `data/model/BeatPattern.kt` — BeatHit + BeatPattern data classes
- `data/model/AnalysisResult.kt` — BPM, key, duration, sample rate
- `data/model/Song.kt` — URI, display name, internal path

**Audio Core (6 files):**
- `audio/decoder/Mp3Decoder.kt` — MP3 → PCM via MediaExtractor/MediaCodec
- `audio/analysis/TempoDetector.kt` — Energy-based BPM detection
- `audio/analysis/KeyDetector.kt` — FFT + Krumhansl-Kessler key profiles
- `audio/engine/AudioEngine.kt` — AudioTrack sequencer with real-time BPM control
- `audio/engine/BeatGenerator.kt` — Pattern generation for all 5 instruments
- `audio/engine/SampleGenerator.kt` — Synthetic WAV-like samples for each instrument
- `audio/export/BeatExporter.kt` — PCM → AAC/M4A via MediaCodec + MediaStore

**UI Screens (3 files):**
- `ui/screens/HomeScreen.kt` — File picker, "Pick a Song" button
- `ui/screens/AnalysisScreen.kt` — Progress indicator, BPM/key results
- `ui/screens/BeatEditorScreen.kt` — Full editor with all controls

**UI Components (3 files):**
- `ui/components/SliderControls.kt` — BPM slider (60-200 range)
- `ui/components/InstrumentPicker.kt` — 5 instrument chips
- `ui/components/TransportBar.kt` — Play/Pause/Stop + beat indicator

**ViewModels (3 files):**
- `viewmodel/HomeViewModel.kt` — Song loading state
- `viewmodel/AnalysisViewModel.kt` — Analysis pipeline orchestration
- `viewmodel/BeatEditorViewModel.kt` — Engine control, export

**Navigation & Utility (2 files):**
- `ui/navigation/NavGraph.kt` — State-based screen navigation
- `util/FileUtils.kt` — Copy URIs to internal storage

---

## Sub-task Completion

- [x] **1a. File Picker** — OpenDocument contract, audio/* filter
- [x] **1b. MP3 Decoding** — MediaExtractor + MediaCodec → PCM floats
- [x] **1c. Tempo Detection** — Energy envelope + onset detection + BPM histogram
- [x] **1d. Key Detection** — FFT chromagram + Krumhansl-Kessler profile matching
- [x] **1e. Analysis Screen** — Progress steps, result card, "Generate Beat" button
- [x] **1f. Beat Pattern Generation** — 5 instrument patterns (drums, tabla, guitar, piano, flute)
- [x] **1g. Audio Engine** — AudioTrack-based sequencer with real-time BPM adjustment
- [x] **1h. Beat Editor Screen** — BPM slider, instrument picker, transport, export button
- [x] **1i. Real-time Playback** — Play/pause/stop, beat position indicator
- [x] **1j. Export** — AAC/M4A encoding, save to Music/Beatz directory
- [x] **1k. Navigation** — State-based Home → Analysis → Editor flow

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| AudioTrack over MWEngine | MWEngine requires NDK/CMake/SWIG build from source — too complex |
| Custom BPM detection over TarsosDSP | TarsosDSP has javax.sound dependency issues on Android |
| AAC/M4A export over MP3 | MediaCodec has built-in AAC encoder, no native LAME needed |
| Synthetic samples over WAV files | No external dependencies, app works immediately |
| State-based nav over Compose Navigation | Simpler for passing complex objects (AnalysisResult) |

---

## What to Test
1. Pick an MP3 from storage → should decode and show BPM/key
2. Tap "Generate Beat" → opens editor with detected BPM
3. Slide BPM → beat timing changes in real-time
4. Switch instruments → different patterns play
5. Export → saves M4A to Music/Beatz folder
