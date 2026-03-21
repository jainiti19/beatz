# Beatz — Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **MWEngine setup complexity** (NDK/CMake) | High | High | Follow wiki step-by-step. Fallback: use `AudioTrack` with manual sample mixing |
| **TarsosDSP Android compatibility** (`javax.sound` unavailable) | Medium | High | Use Android-specific fork (TarsosDSPAndroid) |
| **Tempo detection accuracy** on complex songs | Medium | Medium | Add "tap tempo" manual override; show detected BPM as suggestion |
| **Key detection accuracy** | High | Low | Informational only in Phase 1; let user override |
| **Audio latency on emulator** | High | Medium | Accept emulator limits; test real audio on physical device early |
| **Large APK from audio samples** | Medium | Medium | Start small; use OGG; move to downloadable packs in Phase 4 |
| **Spotify/YouTube legal issues** | High | High | Defer to Phase 4; use "microphone capture" workaround |
| **Kotlin/Android learning curve** | Medium | Medium | Small sub-tasks (2-5 hrs each); well-documented patterns; official codelabs |
