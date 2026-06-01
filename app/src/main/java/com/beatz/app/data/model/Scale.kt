package com.beatz.app.data.model

/**
 * Musical scales with their semitone intervals from the root note.
 * Used to snap melody notes and generate arpeggios/chord tones.
 */
enum class Scale(val displayName: String, val intervals: List<Int>) {
    MAJOR("Major", listOf(0, 2, 4, 5, 7, 9, 11)),
    MINOR("Minor", listOf(0, 2, 3, 5, 7, 8, 10)),
    PENTATONIC_MAJOR("Pentatonic Maj", listOf(0, 2, 4, 7, 9)),
    PENTATONIC_MINOR("Pentatonic Min", listOf(0, 3, 5, 7, 10)),
    BLUES("Blues", listOf(0, 3, 5, 6, 7, 10)),
    HARMONIC_MINOR("Harmonic Min", listOf(0, 2, 3, 5, 7, 8, 11));

    /**
     * Get all MIDI notes in this scale for a given root note, within a range.
     */
    fun getNotesInRange(rootMidi: Int, lowMidi: Int = 48, highMidi: Int = 84): List<Int> {
        val notes = mutableListOf<Int>()
        // Root note's pitch class (0-11)
        val rootPc = rootMidi % 12
        for (midi in lowMidi..highMidi) {
            val pc = ((midi % 12) - rootPc + 12) % 12
            if (pc in intervals) {
                notes.add(midi)
            }
        }
        return notes
    }

    /**
     * Snap a MIDI note to the nearest note in this scale.
     */
    fun snapToScale(midiNote: Int, rootMidi: Int): Int {
        val rootPc = rootMidi % 12
        val pc = ((midiNote % 12) - rootPc + 12) % 12
        if (pc in intervals) return midiNote

        // Find nearest scale degree
        var bestDist = 12
        var bestPc = 0
        for (interval in intervals) {
            val dist = minOf(
                kotlin.math.abs(pc - interval),
                12 - kotlin.math.abs(pc - interval)
            )
            if (dist < bestDist) {
                bestDist = dist
                bestPc = interval
            }
        }

        val snappedPc = (rootPc + bestPc) % 12
        val octave = midiNote / 12
        var snapped = octave * 12 + snappedPc
        // Keep close to original note
        if (snapped > midiNote + 6) snapped -= 12
        if (snapped < midiNote - 6) snapped += 12
        return snapped
    }

    companion object {
        /**
         * Parse a key string like "C major" or "A minor" into root MIDI and scale.
         */
        fun fromKeyString(keyStr: String): Pair<Int, Scale> {
            val parts = keyStr.lowercase().trim().split(" ")
            val noteName = parts.getOrElse(0) { "c" }
            val scaleType = parts.getOrElse(1) { "major" }

            val rootPc = when (noteName) {
                "c" -> 0; "c#", "db" -> 1; "d" -> 2; "d#", "eb" -> 3
                "e" -> 4; "f" -> 5; "f#", "gb" -> 6; "g" -> 7
                "g#", "ab" -> 8; "a" -> 9; "a#", "bb" -> 10; "b" -> 11
                else -> 0
            }
            // Root at octave 4 (MIDI 60 = C4)
            val rootMidi = 60 + rootPc

            val scale = when {
                scaleType.contains("minor") -> MINOR
                else -> MAJOR
            }

            return Pair(rootMidi, scale)
        }
    }
}
