# Current Status

**Date:** 2026-06-01
**Current Phase:** Phase 2 — Bollywood-focused revision in progress
**Next Action:** Phase 2e — Raga system

## What's Done

- Phase 0: Environment setup (Android Studio, SDK, emulator, project scaffold)
- Phase 1: Full MVP (file picker, decode, BPM/key detect, 5 instruments, playback, export)
- Phase 2a: Multi-layer audio engine
- Phase 2b: Layer UI (volume, mute, solo)
- Phase 2c: Scale-aware melody snapping (Western scales)
- Phase 2d: Scale selector UI (Western scales)

## Phase 2 — Revised for Bollywood

After critiquing the approach against Bollywood music requirements, Phase 2 was restructured.
See: `docs/phases/phase-2-bollywood-revised.md` for full details.

**Remaining sub-tasks (in order):**

| # | Sub-phase | Description | Est. Hours |
|---|-----------|-------------|------------|
| 1 | **2e** | Raga system (10 ragas, direction-aware snapping) | 8-10 |
| 2 | **2f** | Taal system (5 taals, 8 tabla bols, variable time) | 12-15 |
| 3 | **2g** | Bollywood instruments (harmonium, sitar, dholak, bansuri) | 10-12 |
| 4 | **2h** | Tanpura drone layer | 6-8 |
| 5 | **2i** | Melody extraction fixes for Bollywood vocals | 3-4 |
| 6 | **2j** | Timber + texture controls | 6-8 |
| 7 | **2k** | Key transposition | 2-3 |

## Technical Notes
- Pure Kotlin (no native code) — AudioTrack engine
- Synthetic instrument samples (programmatic)
- WAV export (AAC had silence issues on emulator)
- 29 Kotlin source files currently
