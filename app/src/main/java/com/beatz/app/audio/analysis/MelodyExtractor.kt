package com.beatz.app.audio.analysis

import com.beatz.app.audio.decoder.DecodedAudio
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.log2
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * A single detected note in the melody.
 * @param timeMs when this note occurs from the start of the song
 * @param midiNote MIDI note number (60 = C4, 69 = A4, etc.)
 * @param noteName human-readable name like "C4", "A#3"
 * @param confidence how strong/clear this note detection is (0.0 to 1.0)
 */
data class MelodyNote(
    val timeMs: Double,
    val midiNote: Int,
    val noteName: String,
    val confidence: Float
)

/**
 * Extracts the dominant melody (pitch sequence) from decoded audio.
 * Uses autocorrelation-based pitch detection (YIN-like algorithm).
 */
object MelodyExtractor {

    private val NOTE_NAMES = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

    /**
     * Extract melody notes from the audio.
     * Returns a list of notes detected over time, quantized to the beat grid.
     * @param bpm detected BPM, used to quantize notes to beat positions
     * @param maxNotes maximum notes to return (limits to first N bars)
     */
    fun extract(audio: DecodedAudio, bpm: Float, maxNotes: Int = 64): List<MelodyNote> {
        // Mix to mono
        val mono = if (audio.channels > 1) {
            FloatArray(audio.samples.size / audio.channels) { i ->
                var sum = 0f
                for (ch in 0 until audio.channels) sum += audio.samples[i * audio.channels + ch]
                sum / audio.channels
            }
        } else {
            audio.samples
        }

        val sampleRate = audio.sampleRate

        // Only analyze the first 15 seconds for speed
        val maxSamples = sampleRate * 15
        val analysisMono = if (mono.size > maxSamples) mono.copyOf(maxSamples) else mono

        // Analyze pitch in windows — use larger hop for speed
        val windowSizeSamples = 4096
        val hopSizeSamples = windowSizeSamples  // No overlap = 2x faster

        val rawNotes = mutableListOf<MelodyNote>()

        var offset = 0
        while (offset + windowSizeSamples < analysisMono.size && rawNotes.size < maxNotes * 4) {
            val window = FloatArray(windowSizeSamples) { i ->
                // Apply Hanning window
                analysisMono[offset + i] * (0.5f - 0.5f * cos(2.0 * PI * i / windowSizeSamples).toFloat())
            }

            val pitchHz = detectPitchAutocorrelation(window, sampleRate)

            if (pitchHz > 0) {
                val timeMs = offset.toDouble() * 1000.0 / sampleRate
                val midiNote = frequencyToMidi(pitchHz)
                val noteName = midiToNoteName(midiNote)
                val rms = sqrt(window.map { it * it }.average().toFloat())
                val confidence = (rms * 10).coerceIn(0f, 1f)

                if (midiNote in 36..96 && confidence > 0.05f) { // C2 to C7
                    rawNotes.add(MelodyNote(timeMs, midiNote, noteName, confidence))
                }
            }

            offset += hopSizeSamples
        }

        // Quantize to beat grid and remove duplicates
        return quantizeToBeats(rawNotes, bpm, maxNotes)
    }

    /**
     * Autocorrelation-based pitch detection (simplified YIN).
     * @return detected frequency in Hz, or -1 if no clear pitch
     */
    private fun detectPitchAutocorrelation(window: FloatArray, sampleRate: Int): Double {
        val n = window.size
        val minPeriod = sampleRate / 1000  // 1000 Hz max
        val maxPeriod = sampleRate / 60    // 60 Hz min

        if (maxPeriod >= n / 2) return -1.0

        // Compute difference function (YIN step 2)
        val diff = DoubleArray(maxPeriod + 1)
        for (tau in 1..maxPeriod) {
            var sum = 0.0
            for (j in 0 until n - maxPeriod) {
                val delta = (window[j] - window[j + tau]).toDouble()
                sum += delta * delta
            }
            diff[tau] = sum
        }

        // Cumulative mean normalized difference (YIN step 3)
        val cmndf = DoubleArray(maxPeriod + 1)
        cmndf[0] = 1.0
        var runningSum = 0.0
        for (tau in 1..maxPeriod) {
            runningSum += diff[tau]
            cmndf[tau] = if (runningSum > 0) diff[tau] * tau / runningSum else 1.0
        }

        // Find the first dip below threshold (YIN step 4)
        val threshold = 0.15
        var bestTau = -1
        for (tau in minPeriod..maxPeriod) {
            if (cmndf[tau] < threshold) {
                // Find the local minimum starting from this dip
                bestTau = tau
                var searchTau = tau
                while (searchTau + 1 <= maxPeriod && cmndf[searchTau + 1] < cmndf[searchTau]) {
                    searchTau++
                }
                bestTau = searchTau
                break
            }
        }

        if (bestTau == -1) {
            // Fallback: find global minimum in range
            var minVal = Double.MAX_VALUE
            for (tau in minPeriod..maxPeriod) {
                if (cmndf[tau] < minVal) {
                    minVal = cmndf[tau]
                    bestTau = tau
                }
            }
            // Only use if it's a clear enough pitch
            if (minVal > 0.4) return -1.0
        }

        return sampleRate.toDouble() / bestTau
    }

    private fun frequencyToMidi(hz: Double): Int {
        return (69 + 12 * log2(hz / 440.0)).roundToInt()
    }

    private fun midiToNoteName(midi: Int): String {
        val note = NOTE_NAMES[((midi % 12) + 12) % 12]
        val octave = (midi / 12) - 1
        return "$note$octave"
    }

    /**
     * Quantize detected notes to the beat grid, keeping the strongest
     * note per eighth-note position. Returns one bar's worth of notes.
     */
    private fun quantizeToBeats(
        rawNotes: List<MelodyNote>,
        bpm: Float,
        maxNotes: Int
    ): List<MelodyNote> {
        if (rawNotes.isEmpty()) return defaultMelody()

        val eighthNoteMs = 30_000.0 / bpm // duration of one eighth note

        // Group notes by eighth-note position
        data class GridSlot(val position: Int, var bestNote: MelodyNote)
        val grid = mutableMapOf<Int, GridSlot>()

        for (note in rawNotes) {
            val pos = (note.timeMs / eighthNoteMs).toInt()
            val existing = grid[pos]
            if (existing == null || note.confidence > existing.bestNote.confidence) {
                grid[pos] = GridSlot(pos, note)
            }
        }

        // Take the first maxNotes unique notes, re-timed to positions within bars
        val barMs = 4 * 60_000.0 / bpm
        val result = mutableListOf<MelodyNote>()
        val sortedSlots = grid.values.sortedBy { it.position }

        // Extract one bar (8 eighth notes) worth of the most common pattern
        // by folding all bars into one
        val notesPerBar = 8
        val foldedGrid = mutableMapOf<Int, MutableList<MelodyNote>>()

        for (slot in sortedSlots) {
            val posInBar = slot.position % notesPerBar
            foldedGrid.getOrPut(posInBar) { mutableListOf() }.add(slot.bestNote)
        }

        // For each position in the bar, pick the most common note (by MIDI number)
        for (pos in 0 until notesPerBar) {
            val notesAtPos = foldedGrid[pos] ?: continue
            // Find the most frequent MIDI note at this position
            val mostCommonMidi = notesAtPos
                .groupBy { it.midiNote }
                .maxByOrNull { it.value.size }
                ?.key ?: continue

            val representative = notesAtPos.first { it.midiNote == mostCommonMidi }
            val timeInBarMs = pos * eighthNoteMs

            result.add(
                MelodyNote(
                    timeMs = timeInBarMs,
                    midiNote = representative.midiNote,
                    noteName = representative.noteName,
                    confidence = representative.confidence
                )
            )

            if (result.size >= maxNotes) break
        }

        return if (result.isEmpty()) defaultMelody() else result.sortedBy { it.timeMs }
    }

    /**
     * Fallback melody if detection fails: C major arpeggio.
     */
    private fun defaultMelody(): List<MelodyNote> {
        return listOf(
            MelodyNote(0.0, 60, "C4", 0.8f),
            MelodyNote(0.0, 64, "E4", 0.7f),  // will be re-timed by BeatGenerator
            MelodyNote(0.0, 67, "G4", 0.7f),
            MelodyNote(0.0, 72, "C5", 0.6f)
        )
    }
}
