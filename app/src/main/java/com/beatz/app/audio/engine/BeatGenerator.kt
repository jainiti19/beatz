package com.beatz.app.audio.engine

import com.beatz.app.audio.analysis.MelodyNote
import com.beatz.app.data.model.BeatHit
import com.beatz.app.data.model.BeatPattern
import com.beatz.app.data.model.Instrument
import com.beatz.app.data.model.Raga
import com.beatz.app.data.model.Scale

/**
 * Generates beat patterns for different instruments at a given BPM.
 * Supports scale-aware melody snapping and arpeggio generation.
 */
object BeatGenerator {

    fun generate(
        instrument: Instrument,
        bpm: Float,
        melodyNotes: List<MelodyNote> = emptyList(),
        scale: Scale? = Scale.MAJOR,
        raga: Raga? = null,
        rootMidi: Int = 60
    ): BeatPattern {
        val beatMs = 60_000.0 / bpm
        val barMs = beatMs * 4

        val hasTwoBarMelody = melodyNotes.any { it.timeMs >= barMs }
        val isMelodic = instrument in listOf(Instrument.GUITAR, Instrument.PIANO, Instrument.FLUTE)
        val patternBars = if (hasTwoBarMelody && isMelodic) 2 else 1
        val patternMs = barMs * patternBars
        val eighthMs = beatMs / 2
        val sixteenthMs = beatMs / 4

        // Snap melody notes to the selected scale or raga
        val scaledMelody = snapMelodyNotes(melodyNotes, scale, raga, rootMidi)

        val hits = when (instrument) {
            Instrument.DRUMS -> {
                val bar1 = generateDrumPattern(beatMs, eighthMs)
                if (patternBars == 2) bar1 + bar1.map { it.copy(timeMs = it.timeMs + barMs) }
                else bar1
            }
            Instrument.TABLA -> {
                val bar1 = generateTablaPattern(beatMs, eighthMs, sixteenthMs)
                if (patternBars == 2) bar1 + bar1.map { it.copy(timeMs = it.timeMs + barMs) }
                else bar1
            }
            Instrument.GUITAR -> {
                if (scaledMelody.isNotEmpty())
                    generateGuitarMelody(beatMs, eighthMs, patternMs, scaledMelody)
                else
                    generateArpeggio("guitar", beatMs, eighthMs, patternMs, scale, raga, rootMidi)
            }
            Instrument.PIANO -> {
                if (scaledMelody.isNotEmpty())
                    generatePianoMelody(beatMs, eighthMs, patternMs, scaledMelody)
                else
                    generateArpeggio("piano", beatMs, eighthMs, patternMs, scale, raga, rootMidi)
            }
            Instrument.FLUTE -> {
                if (scaledMelody.isNotEmpty())
                    generateFluteMelody(beatMs, eighthMs, patternMs, scaledMelody)
                else
                    generateArpeggio("flute", beatMs, eighthMs, patternMs, scale, raga, rootMidi, longNotes = true)
            }
        }

        return BeatPattern(hits = hits, durationMs = patternMs, bpm = bpm)
    }

    // ---- Snap melody notes to scale or raga ----

    private fun snapMelodyNotes(
        notes: List<MelodyNote>, scale: Scale?, raga: Raga?, rootMidi: Int
    ): List<MelodyNote> {
        if (notes.isEmpty()) return notes
        return notes.mapIndexed { index, note ->
            // Detect direction from neighboring notes
            val prevMidi = if (index > 0) notes[index - 1].midiNote else note.midiNote
            val direction = when {
                note.midiNote > prevMidi -> 1   // ascending
                note.midiNote < prevMidi -> -1  // descending
                else -> 0
            }

            val snapped = when {
                raga != null -> raga.snapToRaga(note.midiNote, rootMidi, direction)
                scale != null -> scale.snapToScale(note.midiNote, rootMidi)
                else -> note.midiNote
            }
            note.copy(midiNote = snapped, noteName = midiToNoteName(snapped))
        }
    }

    // ---- Arpeggio generator (scale or raga aware) ----

    private fun generateArpeggio(
        prefix: String,
        beatMs: Double,
        eighthMs: Double,
        patternMs: Double,
        scale: Scale?,
        raga: Raga?,
        rootMidi: Int,
        longNotes: Boolean = false
    ): List<BeatHit> {
        // Get chord tones from raga or scale
        val chordTones = if (raga != null) {
            raga.getChordTones(rootMidi)
        } else {
            val scaleNotes = (scale ?: Scale.MAJOR).getNotesInRange(rootMidi, lowMidi = 60, highMidi = 79)
            if (scaleNotes.isEmpty()) return emptyList()
            val tones = mutableListOf<Int>()
            tones.add(scaleNotes[0])
            if (scaleNotes.size > 2) tones.add(scaleNotes[2])
            if (scaleNotes.size > 4) tones.add(scaleNotes[4])
            tones.add(scaleNotes[0] + 12)
            tones
        }

        val hits = mutableListOf<BeatHit>()
        val numBeats = (patternMs / eighthMs).toInt()

        for (i in 0 until numBeats) {
            val timeMs = i * eighthMs
            if (timeMs >= patternMs) break

            val noteIndex = i % chordTones.size
            val midi = chordTones[noteIndex]
            val velocity = if (i % 2 == 0) 0.85f else 0.6f

            val sampleName = if (longNotes && prefix == "flute") {
                val suffix = if (i % 4 == 0) "long" else "short"
                "${prefix}_${midi}_$suffix"
            } else {
                "${prefix}_$midi"
            }

            // Don't play every slot — leave some space
            if (i % 2 == 0 || (i % 4 == 1)) {
                hits.add(BeatHit(timeMs = timeMs, sampleName = sampleName, velocity = velocity))
            }
        }

        return hits.sortedBy { it.timeMs }
    }

    // ---- Melodic patterns using extracted + scale-snapped notes ----

    private fun generatePianoMelody(
        beatMs: Double, eighthMs: Double, barMs: Double, melodyNotes: List<MelodyNote>
    ): List<BeatHit> {
        val notesToUse = fitNotesToPattern(melodyNotes, eighthMs, barMs)
        return notesToUse.map { note ->
            BeatHit(
                timeMs = note.timeMs,
                sampleName = "piano_${note.midiNote}",
                velocity = note.confidence.coerceIn(0.5f, 1.0f)
            )
        }.sortedBy { it.timeMs }
    }

    private fun generateGuitarMelody(
        beatMs: Double, eighthMs: Double, barMs: Double, melodyNotes: List<MelodyNote>
    ): List<BeatHit> {
        val notesToUse = fitNotesToPattern(melodyNotes, eighthMs, barMs)
        return notesToUse.mapIndexed { index, note ->
            val velocity = if (index % 2 == 0)
                note.confidence.coerceIn(0.6f, 1.0f)
            else
                note.confidence.coerceIn(0.4f, 0.8f)
            BeatHit(
                timeMs = note.timeMs,
                sampleName = "guitar_${note.midiNote}",
                velocity = velocity
            )
        }.sortedBy { it.timeMs }
    }

    private fun generateFluteMelody(
        beatMs: Double, eighthMs: Double, barMs: Double, melodyNotes: List<MelodyNote>
    ): List<BeatHit> {
        val notesToUse = fitNotesToPattern(melodyNotes, eighthMs, barMs)
        return notesToUse.map { note ->
            val isOnBeat = (note.timeMs % beatMs) < (eighthMs * 0.5)
            val suffix = if (isOnBeat) "long" else "short"
            BeatHit(
                timeMs = note.timeMs,
                sampleName = "flute_${note.midiNote}_$suffix",
                velocity = note.confidence.coerceIn(0.5f, 1.0f)
            )
        }.sortedBy { it.timeMs }
    }

    private fun fitNotesToPattern(
        melodyNotes: List<MelodyNote>, eighthMs: Double, patternMs: Double
    ): List<MelodyNote> {
        val withinPattern = melodyNotes.filter { it.timeMs < patternMs }
        if (withinPattern.isNotEmpty()) return withinPattern

        val numSlots = (patternMs / eighthMs).toInt().coerceAtMost(16)
        return melodyNotes.take(numSlots).mapIndexed { index, note ->
            note.copy(timeMs = index * eighthMs)
        }
    }

    // ---- Percussion patterns ----

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
        beatMs: Double, eighthMs: Double, sixteenthMs: Double
    ): List<BeatHit> {
        return listOf(
            BeatHit(timeMs = 0.0, sampleName = "dha", velocity = 1.0f),
            BeatHit(timeMs = 2 * beatMs, sampleName = "dha", velocity = 0.9f),
            BeatHit(timeMs = beatMs, sampleName = "tin", velocity = 0.8f),
            BeatHit(timeMs = 1.5 * beatMs, sampleName = "tin", velocity = 0.5f),
            BeatHit(timeMs = 3 * beatMs, sampleName = "tin", velocity = 0.8f),
            BeatHit(timeMs = 3.5 * beatMs, sampleName = "tin", velocity = 0.5f),
            BeatHit(timeMs = 2.5 * beatMs, sampleName = "dha", velocity = 0.6f)
        ).sortedBy { it.timeMs }
    }

    private val NOTE_NAMES = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

    private fun midiToNoteName(midi: Int): String {
        val note = NOTE_NAMES[((midi % 12) + 12) % 12]
        val octave = (midi / 12) - 1
        return "$note$octave"
    }
}
