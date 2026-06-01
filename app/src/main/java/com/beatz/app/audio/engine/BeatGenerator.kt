package com.beatz.app.audio.engine

import com.beatz.app.audio.analysis.MelodyNote
import com.beatz.app.data.model.BeatHit
import com.beatz.app.data.model.BeatPattern
import com.beatz.app.data.model.Instrument

/**
 * Generates beat patterns for different instruments at a given BPM.
 * Drums and Tabla use rhythmic patterns.
 * Guitar, Piano, and Flute use extracted melody notes from the song.
 */
object BeatGenerator {

    /**
     * Generate a 1-bar (4 beats) pattern.
     * @param melodyNotes extracted melody from the original song (used for Guitar, Piano, Flute)
     */
    fun generate(
        instrument: Instrument,
        bpm: Float,
        melodyNotes: List<MelodyNote> = emptyList()
    ): BeatPattern {
        val beatMs = 60_000.0 / bpm
        val barMs = beatMs * 4
        val eighthMs = beatMs / 2
        val sixteenthMs = beatMs / 4

        val hits = when (instrument) {
            Instrument.DRUMS -> generateDrumPattern(beatMs, eighthMs)
            Instrument.TABLA -> generateTablaPattern(beatMs, eighthMs, sixteenthMs)
            Instrument.GUITAR -> generateGuitarMelody(beatMs, eighthMs, barMs, melodyNotes)
            Instrument.PIANO -> generatePianoMelody(beatMs, eighthMs, barMs, melodyNotes)
            Instrument.FLUTE -> generateFluteMelody(beatMs, eighthMs, barMs, melodyNotes)
        }

        return BeatPattern(hits = hits, durationMs = barMs, bpm = bpm)
    }

    // ---- Melodic patterns using extracted notes ----

    /**
     * Piano melody: plays extracted notes on eighth-note positions.
     * Each note gets a unique sample name "piano_<midiNote>".
     */
    private fun generatePianoMelody(
        beatMs: Double,
        eighthMs: Double,
        barMs: Double,
        melodyNotes: List<MelodyNote>
    ): List<BeatHit> {
        if (melodyNotes.isEmpty()) return generatePianoFallback(beatMs)

        val hits = mutableListOf<BeatHit>()
        val notesToUse = fitNotesToBar(melodyNotes, eighthMs, barMs)

        for (note in notesToUse) {
            hits.add(
                BeatHit(
                    timeMs = note.timeMs,
                    sampleName = "piano_${note.midiNote}",
                    velocity = note.confidence.coerceIn(0.5f, 1.0f)
                )
            )
        }

        return hits.sortedBy { it.timeMs }
    }

    /**
     * Guitar melody: plays extracted notes with strumming feel.
     * Adds slight timing offsets to simulate pick attack.
     */
    private fun generateGuitarMelody(
        beatMs: Double,
        eighthMs: Double,
        barMs: Double,
        melodyNotes: List<MelodyNote>
    ): List<BeatHit> {
        if (melodyNotes.isEmpty()) return generateGuitarFallback(beatMs, eighthMs)

        val hits = mutableListOf<BeatHit>()
        val notesToUse = fitNotesToBar(melodyNotes, eighthMs, barMs)

        for ((index, note) in notesToUse.withIndex()) {
            // Alternate between slightly different velocities for strum feel
            val velocity = if (index % 2 == 0) {
                note.confidence.coerceIn(0.6f, 1.0f)
            } else {
                note.confidence.coerceIn(0.4f, 0.8f)
            }

            hits.add(
                BeatHit(
                    timeMs = note.timeMs,
                    sampleName = "guitar_${note.midiNote}",
                    velocity = velocity
                )
            )
        }

        return hits.sortedBy { it.timeMs }
    }

    /**
     * Flute melody: plays extracted notes with longer sustain on strong beats.
     */
    private fun generateFluteMelody(
        beatMs: Double,
        eighthMs: Double,
        barMs: Double,
        melodyNotes: List<MelodyNote>
    ): List<BeatHit> {
        if (melodyNotes.isEmpty()) return generateFluteFallback(beatMs)

        val hits = mutableListOf<BeatHit>()
        val notesToUse = fitNotesToBar(melodyNotes, eighthMs, barMs)

        for (note in notesToUse) {
            // Strong beats (on beat positions) get long notes, off-beats get short
            val isOnBeat = (note.timeMs % beatMs) < (eighthMs * 0.5)
            val sampleSuffix = if (isOnBeat) "long" else "short"

            hits.add(
                BeatHit(
                    timeMs = note.timeMs,
                    sampleName = "flute_${note.midiNote}_$sampleSuffix",
                    velocity = note.confidence.coerceIn(0.5f, 1.0f)
                )
            )
        }

        return hits.sortedBy { it.timeMs }
    }

    /**
     * Fit the extracted melody notes into one bar's time grid.
     * Spaces them evenly across the bar if their original timing
     * doesn't fit, or uses their quantized positions if they do.
     */
    private fun fitNotesToBar(
        melodyNotes: List<MelodyNote>,
        eighthMs: Double,
        barMs: Double
    ): List<MelodyNote> {
        // If melody notes already have timing within one bar, use them directly
        val withinBar = melodyNotes.filter { it.timeMs < barMs }
        if (withinBar.isNotEmpty()) return withinBar

        // Otherwise, space the notes evenly across the bar on eighth-note positions
        val numSlots = 8 // eighth notes in a bar
        val notesToPlace = melodyNotes.take(numSlots)

        return notesToPlace.mapIndexed { index, note ->
            note.copy(timeMs = index * eighthMs)
        }
    }

    // ---- Fallback patterns (when no melody detected) ----

    private fun generatePianoFallback(beatMs: Double): List<BeatHit> {
        return listOf(
            BeatHit(timeMs = 0.0, sampleName = "piano_60", velocity = 1.0f),
            BeatHit(timeMs = beatMs, sampleName = "piano_64", velocity = 0.7f),
            BeatHit(timeMs = 2 * beatMs, sampleName = "piano_67", velocity = 0.85f),
            BeatHit(timeMs = 3 * beatMs, sampleName = "piano_72", velocity = 0.7f)
        )
    }

    private fun generateGuitarFallback(beatMs: Double, eighthMs: Double): List<BeatHit> {
        return listOf(
            BeatHit(timeMs = 0.0, sampleName = "guitar_60", velocity = 1.0f),
            BeatHit(timeMs = beatMs, sampleName = "guitar_64", velocity = 0.8f),
            BeatHit(timeMs = 1.5 * beatMs, sampleName = "guitar_67", velocity = 0.6f),
            BeatHit(timeMs = 2 * beatMs, sampleName = "guitar_60", velocity = 0.85f),
            BeatHit(timeMs = 3 * beatMs, sampleName = "guitar_64", velocity = 0.8f),
            BeatHit(timeMs = 3.5 * beatMs, sampleName = "guitar_67", velocity = 0.6f)
        )
    }

    private fun generateFluteFallback(beatMs: Double): List<BeatHit> {
        return listOf(
            BeatHit(timeMs = 0.0, sampleName = "flute_72_long", velocity = 1.0f),
            BeatHit(timeMs = 2 * beatMs, sampleName = "flute_76_long", velocity = 0.9f),
            BeatHit(timeMs = 3 * beatMs, sampleName = "flute_79_short", velocity = 0.6f),
            BeatHit(timeMs = 3.5 * beatMs, sampleName = "flute_72_short", velocity = 0.5f)
        )
    }

    // ---- Percussion patterns (unchanged) ----

    private fun generateDrumPattern(beatMs: Double, eighthMs: Double): List<BeatHit> {
        val hits = mutableListOf<BeatHit>()
        for (i in 0..7) {
            hits.add(BeatHit(timeMs = i * eighthMs, sampleName = "hihat", velocity = 0.7f))
        }
        hits.add(BeatHit(timeMs = 0.0, sampleName = "kick", velocity = 1.0f))
        hits.add(BeatHit(timeMs = 2 * beatMs, sampleName = "kick", velocity = 1.0f))
        hits.add(BeatHit(timeMs = beatMs, sampleName = "snare", velocity = 0.9f))
        hits.add(BeatHit(timeMs = 3 * beatMs, sampleName = "snare", velocity = 0.9f))
        return hits.sortedBy { it.timeMs }
    }

    private fun generateTablaPattern(
        beatMs: Double,
        eighthMs: Double,
        sixteenthMs: Double
    ): List<BeatHit> {
        val hits = mutableListOf<BeatHit>()
        hits.add(BeatHit(timeMs = 0.0, sampleName = "dha", velocity = 1.0f))
        hits.add(BeatHit(timeMs = 2 * beatMs, sampleName = "dha", velocity = 0.9f))
        hits.add(BeatHit(timeMs = beatMs, sampleName = "tin", velocity = 0.8f))
        hits.add(BeatHit(timeMs = 1.5 * beatMs, sampleName = "tin", velocity = 0.5f))
        hits.add(BeatHit(timeMs = 3 * beatMs, sampleName = "tin", velocity = 0.8f))
        hits.add(BeatHit(timeMs = 3.5 * beatMs, sampleName = "tin", velocity = 0.5f))
        hits.add(BeatHit(timeMs = 2.5 * beatMs, sampleName = "dha", velocity = 0.6f))
        return hits.sortedBy { it.timeMs }
    }
}
