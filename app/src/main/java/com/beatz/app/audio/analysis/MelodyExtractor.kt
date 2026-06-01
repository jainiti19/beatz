package com.beatz.app.audio.analysis

import com.beatz.app.audio.decoder.DecodedAudio
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log2
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

data class MelodyNote(
    val timeMs: Double,
    val midiNote: Int,
    val noteName: String,
    val confidence: Float
)

/**
 * Extracts the dominant melody (pitch sequence) from decoded audio.
 * Uses band-pass filtering + YIN pitch detection + beat-grid quantization.
 */
object MelodyExtractor {

    private val NOTE_NAMES = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

    fun extract(audio: DecodedAudio, bpm: Float, maxNotes: Int = 64): List<MelodyNote> {
        val sampleRate = audio.sampleRate

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

        // Skip first 3 seconds (intro), analyze up to 20 seconds of melody content
        val skipSamples = (sampleRate * 3).coerceAtMost(mono.size / 2)
        val endSamples = (skipSamples + sampleRate * 20).coerceAtMost(mono.size)
        val segment = mono.copyOfRange(skipSamples, endSamples)

        // Band-pass filter: keep 200-2000 Hz (vocal/melody range)
        val filtered = bandPassFilter(segment, sampleRate, 200.0, 2000.0)

        // Pitch detection with smaller windows and overlap
        val windowSize = 2048  // ~46ms at 44100 Hz
        val hopSize = windowSize / 2  // 50% overlap

        val rawNotes = mutableListOf<MelodyNote>()
        var offset = 0

        while (offset + windowSize < filtered.size && rawNotes.size < maxNotes * 8) {
            val window = FloatArray(windowSize) { i ->
                filtered[offset + i] * (0.5f - 0.5f * cos(2.0 * PI * i / windowSize).toFloat())
            }

            val rms = sqrt(window.map { it * it }.average().toFloat())

            // Only detect pitch if there's enough energy
            if (rms > 0.01f) {
                val pitchHz = detectPitchYIN(window, sampleRate)

                if (pitchHz > 0) {
                    val timeMs = (skipSamples + offset).toDouble() * 1000.0 / sampleRate
                    val midiNote = frequencyToMidi(pitchHz)
                    val confidence = (rms * 8).coerceIn(0f, 1f)

                    // Vocal/melody range: C3 (48) to C6 (84)
                    if (midiNote in 48..84 && confidence > 0.08f) {
                        rawNotes.add(MelodyNote(timeMs, midiNote, midiToNoteName(midiNote), confidence))
                    }
                }
            }

            offset += hopSize
        }

        // Smooth: median filter on MIDI notes to remove outlier jumps
        val smoothed = medianFilterNotes(rawNotes, windowSize = 3)

        // Quantize to beat grid — keep 2 bars worth
        return quantizeToBeats(smoothed, bpm, maxNotes)
    }

    /**
     * Simple band-pass filter using cascaded first-order high-pass and low-pass.
     */
    private fun bandPassFilter(samples: FloatArray, sampleRate: Int, lowCutHz: Double, highCutHz: Double): FloatArray {
        val result = FloatArray(samples.size)

        // High-pass filter (remove below lowCutHz)
        val rcHigh = 1.0 / (2.0 * PI * lowCutHz)
        val dtHigh = 1.0 / sampleRate
        val alphaHigh = rcHigh / (rcHigh + dtHigh)

        var prevInput = samples[0].toDouble()
        var prevOutput = samples[0].toDouble()
        result[0] = samples[0]

        for (i in 1 until samples.size) {
            val input = samples[i].toDouble()
            prevOutput = alphaHigh * (prevOutput + input - prevInput)
            prevInput = input
            result[i] = prevOutput.toFloat()
        }

        // Low-pass filter (remove above highCutHz)
        val rcLow = 1.0 / (2.0 * PI * highCutHz)
        val dtLow = 1.0 / sampleRate
        val alphaLow = dtLow / (rcLow + dtLow)

        val output = FloatArray(samples.size)
        output[0] = result[0]
        for (i in 1 until result.size) {
            output[i] = (output[i - 1] + alphaLow * (result[i] - output[i - 1])).toFloat()
        }

        return output
    }

    /**
     * Median filter on MIDI note values to remove outlier pitch jumps.
     */
    private fun medianFilterNotes(notes: List<MelodyNote>, windowSize: Int): List<MelodyNote> {
        if (notes.size < windowSize) return notes

        val result = mutableListOf<MelodyNote>()
        val half = windowSize / 2

        for (i in notes.indices) {
            val start = (i - half).coerceAtLeast(0)
            val end = (i + half).coerceAtMost(notes.size - 1)
            val neighbors = (start..end).map { notes[it].midiNote }.sorted()
            val medianMidi = neighbors[neighbors.size / 2]

            // Only keep notes close to the local median (within 4 semitones)
            if (kotlin.math.abs(notes[i].midiNote - medianMidi) <= 4) {
                result.add(notes[i])
            }
        }

        return result
    }

    /**
     * YIN pitch detection.
     */
    private fun detectPitchYIN(window: FloatArray, sampleRate: Int): Double {
        val n = window.size
        val minPeriod = sampleRate / 1000  // 1000 Hz max
        val maxPeriod = sampleRate / 100   // 100 Hz min (tighter range for melody)

        if (maxPeriod >= n / 2) return -1.0

        // Difference function
        val diff = DoubleArray(maxPeriod + 1)
        for (tau in 1..maxPeriod) {
            var sum = 0.0
            for (j in 0 until n - maxPeriod) {
                val delta = (window[j] - window[j + tau]).toDouble()
                sum += delta * delta
            }
            diff[tau] = sum
        }

        // Cumulative mean normalized difference
        val cmndf = DoubleArray(maxPeriod + 1)
        cmndf[0] = 1.0
        var runningSum = 0.0
        for (tau in 1..maxPeriod) {
            runningSum += diff[tau]
            cmndf[tau] = if (runningSum > 0) diff[tau] * tau / runningSum else 1.0
        }

        // Find first dip below threshold
        val threshold = 0.12  // Stricter threshold for cleaner detection
        var bestTau = -1
        for (tau in minPeriod..maxPeriod) {
            if (cmndf[tau] < threshold) {
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
            // Fallback: global minimum with stricter requirement
            var minVal = Double.MAX_VALUE
            for (tau in minPeriod..maxPeriod) {
                if (cmndf[tau] < minVal) {
                    minVal = cmndf[tau]
                    bestTau = tau
                }
            }
            if (minVal > 0.3) return -1.0
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
     * Quantize notes to the beat grid. Keep 2 bars with 16th-note resolution.
     */
    private fun quantizeToBeats(
        rawNotes: List<MelodyNote>,
        bpm: Float,
        maxNotes: Int
    ): List<MelodyNote> {
        if (rawNotes.isEmpty()) return defaultMelody(bpm)

        val sixteenthMs = 15_000.0 / bpm  // duration of one 16th note
        val barMs = 4 * 60_000.0 / bpm
        val slotsPerBar = 16
        val totalSlots = slotsPerBar * 2  // 2 bars

        // Group notes by 16th-note position across all detected time
        data class GridSlot(val position: Int, var bestNote: MelodyNote)
        val grid = mutableMapOf<Int, GridSlot>()

        for (note in rawNotes) {
            val globalPos = (note.timeMs / sixteenthMs).toInt()
            val posInTwoBars = globalPos % totalSlots
            val existing = grid[posInTwoBars]
            if (existing == null || note.confidence > existing.bestNote.confidence) {
                grid[posInTwoBars] = GridSlot(posInTwoBars, note)
            }
        }

        // Build the 2-bar melody
        val result = mutableListOf<MelodyNote>()
        for (pos in 0 until totalSlots) {
            val slot = grid[pos] ?: continue
            val timeInPatternMs = pos * sixteenthMs

            result.add(
                MelodyNote(
                    timeMs = timeInPatternMs,
                    midiNote = slot.bestNote.midiNote,
                    noteName = slot.bestNote.noteName,
                    confidence = slot.bestNote.confidence
                )
            )

            if (result.size >= maxNotes) break
        }

        return if (result.isEmpty()) defaultMelody(bpm) else result.sortedBy { it.timeMs }
    }

    private fun defaultMelody(bpm: Float): List<MelodyNote> {
        val beatMs = 60_000.0 / bpm
        return listOf(
            MelodyNote(0.0, 60, "C4", 0.8f),
            MelodyNote(beatMs, 64, "E4", 0.7f),
            MelodyNote(beatMs * 2, 67, "G4", 0.7f),
            MelodyNote(beatMs * 3, 72, "C5", 0.6f)
        )
    }
}
