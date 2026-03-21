# Phase 1: MVP

**Status:** NOT STARTED
**Estimated Effort:** 30-40 hours (2-3 weeks part-time)
**Goal:** Pick an MP3 → detect tempo/key → generate drum beat → adjust with sliders → play in real-time → export as MP3.

---

## Architecture

```
HomeScreen          AnalysisScreen         BeatEditorScreen
[Pick Song] ------> [Analyzing...] ------> [Sliders + Play/Export]
     |                    |                       |
HomeViewModel      AnalysisViewModel      BeatEditorViewModel
     |                    |                       |
     v                    v                       v
FileUtils          Mp3Decoder             AudioEngine (MWEngine)
                   TempoDetector          BeatGenerator
                   KeyDetector            InstrumentManager
                                          Mp3Exporter
```

---

## Sub-task Details

### 1a. File Picker (2-3 hours)

**What you'll learn:** Android permissions, file picker intents, Jetpack Compose basics.

**Files to create/edit:**
- `AndroidManifest.xml` — add permissions
- `ui/screens/HomeScreen.kt` — "Pick a Song" button
- `viewmodel/HomeViewModel.kt` — holds selected song state

**Key code concepts:**
- `ActivityResultContracts.OpenDocument` — launches system file picker
- `contentResolver.openInputStream(uri)` — reads the selected file
- Copy to `context.filesDir` so we have permanent access

---

### 1b. MP3 Decoding (3-4 hours)

**What you'll learn:** Android's media APIs, PCM audio basics.

**Files to create:**
- `audio/decoder/Mp3Decoder.kt`

**Key concepts:**
- `MediaExtractor` reads the MP3 container
- `MediaCodec` decodes compressed audio to raw PCM (16-bit samples)
- Output: `ShortArray` of PCM samples + sample rate + channel count

---

### 1c. Tempo Detection (3-4 hours)

**What you'll learn:** Audio analysis, BPM detection.

**Files to create:**
- `audio/analysis/TempoDetector.kt`

**Library:** TarsosDSPAndroid

**Key concepts:**
- Create an `AudioDispatcher` from the PCM data
- Attach `PercussionOnsetDetector` — fires callback on each detected beat
- Collect onset timestamps, calculate average interval, convert to BPM
- **Tip:** Test with a metronome recording first to verify accuracy

---

### 1d. Key Detection (2-3 hours)

**Files to create:**
- `audio/analysis/KeyDetector.kt`

**Key concepts:**
- Use TarsosDSP `PitchProcessor` (YIN algorithm)
- Build histogram of detected pitch classes (C, C#, D, etc.)
- Most frequent pitch class ≈ key (rough estimate, good enough for Phase 1)
- Allow user to override in the editor

---

### 1e. Analysis Screen UI (2-3 hours)

**Files to create:**
- `ui/screens/AnalysisScreen.kt`
- `viewmodel/AnalysisViewModel.kt`

**Shows:** Progress bar → detected BPM → detected key → "Generate Beat" button

---

### 1f. Beat Pattern Generation (4-5 hours)

**Files to create:**
- `data/model/BeatPattern.kt`
- `audio/engine/BeatGenerator.kt`

**Default drum pattern (4/4 time):**
```
Beat:    1   &   2   &   3   &   4   &
Kick:    X       .       X       .
Snare:   .       .       X       .       .       .       X       .
Hi-hat:  X   X   X   X   X   X   X   X
```

Timing calculated from BPM: `interval = 60.0 / bpm` seconds per beat.

---

### 1g. Audio Engine Integration (5-6 hours)

**Files to create:**
- `audio/engine/AudioEngine.kt`
- `audio/engine/InstrumentManager.kt`

**This is the hardest sub-task.** MWEngine setup requires:
1. Add MWEngine dependency (AAR or source via CMake)
2. Initialize engine with sample rate 44100, buffer size 512-1024
3. Load WAV samples into `SampleManager`
4. Create `SampledInstrument` and schedule hits from `BeatPattern`
5. Play/pause/stop controls

**Fallback plan:** If MWEngine proves too complex, use Android's `AudioTrack` API with manual sample mixing.

---

### 1h. Beat Editor Screen (4-5 hours)

**Files to create:**
- `ui/screens/BeatEditorScreen.kt`
- `viewmodel/BeatEditorViewModel.kt`
- `ui/components/SliderControls.kt`
- `ui/components/InstrumentPicker.kt`
- `ui/components/TransportBar.kt`

**UI Layout:**
```
┌─────────────────────────────┐
│  Detected Key: C major      │
│                              │
│  BPM: [====●========] 120   │
│                              │
│  Instrument: [Drums ▼]      │
│                              │
│     [⏮] [▶ Play] [⏭]       │
│                              │
│     [📤 Export as MP3]       │
└─────────────────────────────┘
```

---

### 1i. Real-time Playback (2-3 hours)

- Wire transport buttons to AudioEngine
- BPM slider changes update the sequencer tempo live
- Beat position indicator (pulsing dot or counter)
- Handle audio focus (so music pauses when a call comes in)

---

### 1j. MP3 Export (3-4 hours)

**Files to create:**
- `audio/export/Mp3Exporter.kt`

**Steps:**
1. Render beat pattern to PCM buffer (offline mix)
2. Encode with TAndroidLame → MP3
3. Save to `MediaStore.Audio` (appears in Music folder)
4. Show share intent

---

### 1k. Navigation & Polish (2-3 hours)

- Set up Compose Navigation: Home → Analysis → BeatEditor
- Error handling for file not found, decoding failures
- Loading indicators

---

## Audio Samples Needed (bundle in `assets/samples/`)

| Sample | File |
|--------|------|
| Kick drum | `drums/kick.wav` |
| Snare drum | `drums/snare.wav` |
| Hi-hat closed | `drums/hihat_closed.wav` |
| Hi-hat open | `drums/hihat_open.wav` |
| Tabla (dha) | `tabla/dha.wav` |
| Tabla (tin) | `tabla/tin.wav` |
| Guitar strum | `guitar/strum.wav` |
| Piano chord C | `piano/chord_c.wav` |
| Flute note C | `flute/note_c.wav` |

Source: freesound.org (CC0 license) or similar free sample sites.

---

## End-of-Phase Demo
You can: pick an MP3 → see its BPM and key → hear a drum beat matching that BPM → slide the BPM up/down and hear it change in real-time → switch to tabla/piano/guitar/flute sounds → export the beat as an MP3 and share it.
