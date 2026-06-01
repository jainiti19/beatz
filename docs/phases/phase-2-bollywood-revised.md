# Phase 2 — Revised Plan for Bollywood Music Support

**Date:** 2026-06-01
**Goal:** Make Beatz actually sound like Bollywood, not just generic Western beats.

## Progress So Far

| Sub-phase | Description | Status |
|-----------|-------------|--------|
| 2a | Multi-layer engine (AudioTrack mixer) | DONE |
| 2b | Layer UI (volume, mute, solo) | DONE |
| 2c | Scale-aware melody + snapping | DONE (Western scales only) |
| 2d | Scale selector UI | DONE (Western scales only) |
| 2e | Timber control | NOT STARTED |
| 2f | Texture control | NOT STARTED |
| 2g | Key transposition | NOT STARTED |

## What's Missing for Bollywood

The current implementation uses Western music theory (Major/Minor scales, 4/4 time, basic kick/snare/hihat patterns). Bollywood music is built on Indian classical foundations — ragas, taals, ornaments, and specific instruments. Without these, output won't sound Bollywood.

---

## Revised Phase 2 Sub-tasks

### Phase 2e: Raga System (replaces old 2e Timber)
**Priority: HIGH — biggest impact on Bollywood sound**

Add 10 common Bollywood ragas alongside existing Western scales. Each raga defines:
- **Aroha** (ascending notes) and **Avaroha** (descending notes)
- **Vadi** (most important note) and **Samvadi** (second most important)
- Direction-aware snapping (snap differently going up vs down)

**Ragas to add:**
1. Yaman (Kalyan) — happy, evening, very common in Bollywood
2. Bhairavi — emotional, morning, used in sad songs
3. Khamaj — romantic, light classical
4. Kafi — folk, rain songs
5. Bilawal — bright, similar to Major but with Indian phrasing
6. Bhimpalasi — afternoon, longing
7. Des — patriotic, upbeat
8. Malkauns — serious, late night
9. Bageshri — romantic, night
10. Pilu — semi-classical, very flexible for film music

**Files to change:**
- `Scale.kt` → Add `Raga` class with aroha/avaroha + direction-aware snapping
- `BeatGenerator.kt` → Use direction-aware note selection for melodic instruments
- `ScaleSelector.kt` → Add "Raga" tab alongside Western scales
- `MelodyExtractor.kt` → Raga-aware note snapping (direction detection)

**Estimated effort:** 8-10 hours

---

### Phase 2f: Taal System (replaces old 2f Texture)
**Priority: HIGH — Bollywood rhythm is not 4/4**

Replace hardcoded 4/4 assumption with a flexible taal/time-signature system.

**Taals to add:**
1. **Teentaal** — 16 beats (4+4+4+4), most common in Bollywood
2. **Dadra** — 6 beats (3+3), light songs, ghazals
3. **Keherwa** — 8 beats (4+4), folk, dance numbers
4. **Rupak** — 7 beats (3+2+2), elegant
5. **Jhaptaal** — 10 beats (2+3+2+3), classical crossover

Each taal defines:
- Beat count and grouping (vibhag)
- Sam (beat 1, strongest) and Khali (empty beat)
- Theka — the canonical bol pattern

**Tabla bols to add (minimum):**
| Bol | Sound | Current? |
|-----|-------|----------|
| Dha | bass + ring | YES (basic) |
| Dhin | bass + ring (variant) | NO |
| Tin/Ta | ring only | YES (basic) |
| Na | sharp ring | NO |
| Tun | deep bass | NO |
| Ge/Ghe | bass only | NO |
| Ke/Ka | dry tap | NO |
| Ti | light ring | NO |

**Files to change:**
- New: `Taal.kt` — taal definitions with beat counts, vibhag, theka patterns
- `BeatGenerator.kt` → Use taal structure instead of hardcoded 4-beat bars
- `SampleGenerator.kt` → Add Dhin, Na, Tun, Ge, Ke, Ti synth samples
- `AudioEngine.kt` → Support variable beats-per-bar in playLoop()
- `BeatEditorViewModel.kt` → Add taal selection state
- `BeatEditorScreen.kt` → Add taal picker UI

**Estimated effort:** 12-15 hours

---

### Phase 2g: Bollywood Instruments
**Priority: MEDIUM — adds authenticity**

Add 4 new instruments common in Bollywood:

1. **Harmonium** — sustained organ-like tone with slight tremolo
   - Synth: additive (fundamental + harmonics) with slow attack, sustained envelope
   - Role: melody + drone accompaniment

2. **Sitar** — plucked with sympathetic string buzz
   - Synth: modified Karplus-Strong with sympathetic resonance simulation
   - Role: melody, can do meend (slides between notes)

3. **Dholak** — two-sided hand drum, deeper than tabla
   - Synth: lower-pitched membrane model
   - Bols: Ge (bass), Na (treble), Dhin (both)
   - Role: rhythm (folk/dance songs)

4. **Bansuri** (Indian flute) — breathy, with slides
   - Synth: sine + noise + vibrato (wider than Western flute) + pitch slides
   - Role: melody, ornamental

**Files to change:**
- `Instrument.kt` → Add HARMONIUM, SITAR, DHOLAK, BANSURI
- `SampleGenerator.kt` → Add synth methods for each
- `BeatGenerator.kt` → Add pattern generators for each
- `InstrumentPicker.kt` → Show new instruments in UI

**Estimated effort:** 10-12 hours

---

### Phase 2h: Tanpura Drone Layer
**Priority: MEDIUM — foundational to Indian music feel**

Add a continuous drone layer (not beat-based) that plays Sa-Pa-Sa or Sa-Ma-Sa.

- Drone is a special layer type: continuous audio, not hit-based
- Frequency tracks the root note (key)
- Tanpura synth: plucked string model with very long sustain + jawari buzz

**Files to change:**
- `AudioEngine.kt` → Add drone audio generation alongside beat mixing
- `SampleGenerator.kt` → Add tanpura string synth
- `Layer.kt` → Add `isDrone` flag or a `LayerType` enum
- `BeatEditorViewModel.kt` → Toggle drone on/off
- `BeatEditorScreen.kt` → Drone toggle in UI

**Estimated effort:** 6-8 hours

---

### Phase 2i: Melody Extraction Improvements for Bollywood
**Priority: MEDIUM — better extraction = better output**

Current issues with Bollywood vocal extraction:
- Median filter kills large jumps (common in Bollywood singing)
- 16th-note quantization loses fast ornamental runs (taans)
- YIN threshold too strict for reverb-heavy Bollywood production

**Changes:**
- Widen median filter tolerance from 4 to 7 semitones
- Add 32nd-note quantization option for fast passages
- Lower YIN threshold from 0.12 to 0.15
- Detect note direction (ascending/descending) for raga-aware snapping

**Files to change:**
- `MelodyExtractor.kt` → Relax filters, add direction detection

**Estimated effort:** 3-4 hours

---

### Phase 2j: Timber + Texture Controls (original 2e + 2f)
**Priority: LOWER — nice to have, not Bollywood-specific**

- Timber: low-pass / high-pass filter per layer
- Texture: density slider (note frequency) + reverb slider

**Files to change:**
- `AudioEngine.kt` → Add per-layer filter
- `Layer.kt` → Add timber/texture parameters
- `BeatEditorScreen.kt` → Add sliders

**Estimated effort:** 6-8 hours

---

### Phase 2k: Key Transposition (original 2g)
**Priority: LOWER — straightforward**

- Transpose root note by +/- semitones
- Re-snap all melody notes and regenerate patterns

**Files to change:**
- `BeatEditorViewModel.kt` → Add transpose function
- `BeatEditorScreen.kt` → +/- buttons

**Estimated effort:** 2-3 hours

---

## Recommended Build Order

```
Phase 2e (Ragas)        ←── do first, biggest Bollywood impact
  ↓
Phase 2f (Taals)        ←── second, fixes rhythm foundation
  ↓
Phase 2g (Instruments)  ←── third, adds sonic variety
  ↓
Phase 2h (Drone)        ←── fourth, adds Indian ambiance
  ↓
Phase 2i (Melody fix)   ←── fifth, improves extraction quality
  ↓
Phase 2j (Timber/Texture) ←── sixth, polish
  ↓
Phase 2k (Transpose)    ←── seventh, quick win
```

## Total Estimated Effort

| Sub-phase | Hours |
|-----------|-------|
| 2e Ragas | 8-10 |
| 2f Taals | 12-15 |
| 2g Instruments | 10-12 |
| 2h Drone | 6-8 |
| 2i Melody fix | 3-4 |
| 2j Timber/Texture | 6-8 |
| 2k Transpose | 2-3 |
| **Total** | **47-60 hours** |
