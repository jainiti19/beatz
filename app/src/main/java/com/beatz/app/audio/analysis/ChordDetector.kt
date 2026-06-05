package com.beatz.app.audio.analysis

import com.beatz.app.audio.decoder.DecodedAudio
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log2
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * A detected chord segment: chord name + time range.
 */
data class ChordSegment(
    val chord: String,
    val startTime: Float,
    val endTime: Float
)

/**
 * Detects chord progression from audio using chromagram analysis + template matching.
 *
 * Pipeline:
 * 1. Decode to mono PCM
 * 2. Windowed FFT → 12-bin chroma vectors (one per time window)
 * 3. Match each chroma vector against chord templates (major, minor, 7th, dim)
 * 4. Smooth results (merge short segments, remove jitter)
 * 5. Output: List<ChordSegment> covering the full song
 */
object ChordDetector {

    private val NOTE_NAMES = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

    // Chord templates: each is a 12-element array representing pitch class presence
    // 1.0 = strong, 0.5 = moderate, 0.0 = absent
    private data class ChordTemplate(val suffix: String, val intervals: DoubleArray)

    private val CHORD_TYPES = listOf(
        // Major triad: root, major 3rd, perfect 5th
        ChordTemplate("", doubleArrayOf(1.0, 0.0, 0.0, 0.0, 0.8, 0.0, 0.0, 0.7, 0.0, 0.0, 0.0, 0.0)),
        // Minor triad: root, minor 3rd, perfect 5th
        ChordTemplate("m", doubleArrayOf(1.0, 0.0, 0.0, 0.8, 0.0, 0.0, 0.0, 0.7, 0.0, 0.0, 0.0, 0.0)),
        // Dominant 7th: root, major 3rd, perfect 5th, minor 7th
        ChordTemplate("7", doubleArrayOf(1.0, 0.0, 0.0, 0.0, 0.8, 0.0, 0.0, 0.7, 0.0, 0.0, 0.6, 0.0)),
        // Minor 7th: root, minor 3rd, perfect 5th, minor 7th
        ChordTemplate("m7", doubleArrayOf(1.0, 0.0, 0.0, 0.8, 0.0, 0.0, 0.0, 0.7, 0.0, 0.0, 0.6, 0.0)),
        // Diminished: root, minor 3rd, diminished 5th
        ChordTemplate("dim", doubleArrayOf(1.0, 0.0, 0.0, 0.8, 0.0, 0.0, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0)),
        // Suspended 4th: root, perfect 4th, perfect 5th
        ChordTemplate("sus4", doubleArrayOf(1.0, 0.0, 0.0, 0.0, 0.0, 0.8, 0.0, 0.7, 0.0, 0.0, 0.0, 0.0)),
    )

    // Pre-build all 72 templates (12 roots x 6 types)
    private data class NamedTemplate(val name: String, val profile: DoubleArray)

    private val ALL_TEMPLATES: List<NamedTemplate> = buildList {
        for (root in 0..11) {
            for (type in CHORD_TYPES) {
                val rotated = DoubleArray(12) { i -> type.intervals[(i - root + 12) % 12] }
                add(NamedTemplate("${NOTE_NAMES[root]}${type.suffix}", rotated))
            }
        }
    }

    /**
     * Detect chord progression for the full song.
     * @param audio decoded PCM audio
     * @param maxSeconds if > 0, only analyze this many seconds (0 = full song)
     * @return list of ChordSegments covering the analyzed duration
     */
    fun detect(audio: DecodedAudio, maxSeconds: Float = 0f): List<ChordSegment> {
        val mono = toMono(audio)

        val analysisSamples = if (maxSeconds > 0) {
            val maxSamp = (maxSeconds * audio.sampleRate).toInt()
            if (mono.size > maxSamp) mono.copyOf(maxSamp) else mono
        } else mono

        // Chromagram parameters
        val fftSize = 8192  // ~186ms at 44100Hz — good frequency resolution for chords
        val hopSize = 4096  // ~93ms hop — gives ~10 chroma frames per second
        val numFrames = (analysisSamples.size - fftSize) / hopSize

        if (numFrames <= 0) return listOf(ChordSegment("N/C", 0f, audio.durationSeconds))

        // Step 1: Compute per-frame chroma vectors
        val chromaFrames = Array(numFrames) { DoubleArray(12) }
        for (f in 0 until numFrames) {
            val offset = f * hopSize
            chromaFrames[f] = computeChroma(analysisSamples, offset, fftSize, audio.sampleRate)
        }

        // Step 2: Match each frame to best chord
        val frameChords = Array(numFrames) { f ->
            matchChord(chromaFrames[f])
        }

        // Step 3: Smooth — median filter over 5 frames (~0.5s) to reduce jitter
        val smoothed = medianFilter(frameChords, windowSize = 5)

        // Step 4: Build timeline segments
        val frameTime = hopSize.toFloat() / audio.sampleRate
        val raw = buildSegments(smoothed, frameTime)

        // Step 5: Merge short segments (< 0.5s) into neighbors
        return mergeShortSegments(raw, minDuration = 0.5f)
    }

    private fun toMono(audio: DecodedAudio): FloatArray {
        if (audio.channels <= 1) return audio.samples
        return FloatArray(audio.samples.size / audio.channels) { i ->
            var sum = 0f
            for (ch in 0 until audio.channels) sum += audio.samples[i * audio.channels + ch]
            sum / audio.channels
        }
    }

    /**
     * Compute 12-bin chroma vector from a windowed FFT.
     */
    private fun computeChroma(samples: FloatArray, offset: Int, fftSize: Int, sampleRate: Int): DoubleArray {
        val chroma = DoubleArray(12)

        // Apply Hanning window and compute FFT
        val windowed = FloatArray(fftSize) { i ->
            val idx = offset + i
            if (idx < samples.size) {
                samples[idx] * (0.5f - 0.5f * cos(2.0 * PI * i / fftSize).toFloat())
            } else 0f
        }

        val magnitudes = computeFFTMagnitudes(windowed)

        // Map frequency bins to pitch classes
        // Focus on musical range: ~65Hz (C2) to ~2000Hz (B6)
        for (bin in 1 until magnitudes.size) {
            val freq = bin.toDouble() * sampleRate / fftSize
            if (freq < 65 || freq > 2000) continue

            val mag = magnitudes[bin]
            if (mag < 0.001) continue  // Skip near-silence

            val midiNote = 69.0 + 12.0 * log2(freq / 440.0)
            val pitchClass = ((midiNote.roundToInt() % 12) + 12) % 12
            chroma[pitchClass] += mag
        }

        // Normalize to unit vector
        val norm = sqrt(chroma.sumOf { it * it })
        if (norm > 0) {
            for (i in chroma.indices) chroma[i] /= norm
        }

        return chroma
    }

    /**
     * Match a chroma vector to the best chord template using cosine similarity.
     */
    private fun matchChord(chroma: DoubleArray): String {
        var bestName = "N/C"
        var bestScore = 0.3  // Minimum threshold — below this we call it "no chord"

        for (template in ALL_TEMPLATES) {
            val score = cosineSimilarity(chroma, template.profile)
            if (score > bestScore) {
                bestScore = score
                bestName = template.name
            }
        }

        return bestName
    }

    private fun cosineSimilarity(a: DoubleArray, b: DoubleArray): Double {
        var dot = 0.0
        var normA = 0.0
        var normB = 0.0
        for (i in a.indices) {
            dot += a[i] * b[i]
            normA += a[i] * a[i]
            normB += b[i] * b[i]
        }
        val denom = sqrt(normA) * sqrt(normB)
        return if (denom > 0) dot / denom else 0.0
    }

    /**
     * Majority-vote median filter to smooth chord labels.
     */
    private fun medianFilter(chords: Array<String>, windowSize: Int): Array<String> {
        val half = windowSize / 2
        return Array(chords.size) { i ->
            val start = maxOf(0, i - half)
            val end = minOf(chords.size - 1, i + half)
            // Most common chord in window
            val counts = mutableMapOf<String, Int>()
            for (j in start..end) {
                counts[chords[j]] = (counts[chords[j]] ?: 0) + 1
            }
            counts.maxByOrNull { it.value }?.key ?: chords[i]
        }
    }

    /**
     * Convert per-frame chord labels into ChordSegments.
     */
    private fun buildSegments(chords: Array<String>, frameTime: Float): List<ChordSegment> {
        if (chords.isEmpty()) return emptyList()

        val segments = mutableListOf<ChordSegment>()
        var currentChord = chords[0]
        var startFrame = 0

        for (i in 1 until chords.size) {
            if (chords[i] != currentChord) {
                segments.add(ChordSegment(currentChord, startFrame * frameTime, i * frameTime))
                currentChord = chords[i]
                startFrame = i
            }
        }
        // Final segment
        segments.add(ChordSegment(currentChord, startFrame * frameTime, chords.size * frameTime))

        return segments
    }

    /**
     * Merge segments shorter than minDuration into the previous segment.
     */
    private fun mergeShortSegments(segments: List<ChordSegment>, minDuration: Float): List<ChordSegment> {
        if (segments.size <= 1) return segments

        val merged = mutableListOf<ChordSegment>()
        for (seg in segments) {
            val duration = seg.endTime - seg.startTime
            if (duration < minDuration && merged.isNotEmpty()) {
                // Extend previous segment
                val prev = merged.removeLast()
                merged.add(prev.copy(endTime = seg.endTime))
            } else {
                merged.add(seg)
            }
        }
        return merged
    }

    /**
     * Radix-2 FFT returning magnitude spectrum (positive frequencies only).
     */
    private fun computeFFTMagnitudes(input: FloatArray): DoubleArray {
        val n = input.size
        val real = DoubleArray(n) { input[it].toDouble() }
        val imag = DoubleArray(n)

        // Bit-reversal permutation
        var j = 0
        for (i in 0 until n) {
            if (i < j) {
                val tr = real[i]; real[i] = real[j]; real[j] = tr
                val ti = imag[i]; imag[i] = imag[j]; imag[j] = ti
            }
            var m = n / 2
            while (m >= 1 && j >= m) { j -= m; m /= 2 }
            j += m
        }

        // Cooley-Tukey
        var step = 1
        while (step < n) {
            val halfStep = step
            step *= 2
            val angle = -PI / halfStep
            val wR = cos(angle)
            val wI = sin(angle)
            for (k in 0 until n step step) {
                var uR = 1.0; var uI = 0.0
                for (m2 in 0 until halfStep) {
                    val t = k + m2
                    val tph = t + halfStep
                    val tR = uR * real[tph] - uI * imag[tph]
                    val tI = uR * imag[tph] + uI * real[tph]
                    real[tph] = real[t] - tR
                    imag[tph] = imag[t] - tI
                    real[t] += tR
                    imag[t] += tI
                    val newUR = uR * wR - uI * wI
                    uI = uR * wI + uI * wR
                    uR = newUR
                }
            }
        }

        return DoubleArray(n / 2) { i -> sqrt(real[i] * real[i] + imag[i] * imag[i]) }
    }
}
