package com.beatz.app.audio.analysis

import com.beatz.app.audio.decoder.DecodedAudio
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log2
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Detects the musical key of audio using FFT-based pitch class histogram.
 * Pure Kotlin implementation — rough estimate suitable for Phase 1.
 */
object KeyDetector {

    private val NOTE_NAMES = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

    // Krumhansl-Kessler major and minor key profiles for matching
    private val MAJOR_PROFILE = doubleArrayOf(6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
    private val MINOR_PROFILE = doubleArrayOf(6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

    /**
     * Detect the musical key.
     * @return key string like "C major" or "A minor"
     */
    fun detectKey(audio: DecodedAudio): String {
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

        // Limit to first 15 seconds for speed
        val maxSamples = audio.sampleRate * 15
        val analysisMono = if (mono.size > maxSamples) mono.copyOf(maxSamples) else mono

        // Build pitch class histogram from multiple windows
        val chromagram = DoubleArray(12)
        val fftSize = 4096
        val hopSize = 4096  // No overlap for speed
        val numWindows = (analysisMono.size - fftSize) / hopSize

        if (numWindows <= 0) return "C major"

        for (w in 0 until minOf(numWindows, 100)) {
            val offset = w * hopSize
            val window = FloatArray(fftSize) { i ->
                if (offset + i < analysisMono.size) {
                    // Apply Hanning window
                    mono[offset + i] * (0.5f - 0.5f * cos(2.0 * PI * i / fftSize).toFloat())
                } else 0f
            }

            // Compute magnitude spectrum via FFT
            val magnitudes = computeFFTMagnitudes(window)

            // Map frequency bins to pitch classes
            for (bin in 1 until magnitudes.size) {
                val freq = bin.toDouble() * audio.sampleRate / fftSize
                if (freq < 60 || freq > 4000) continue // Musical range

                val midiNote = 69 + 12 * log2(freq / 440.0)
                val pitchClass = ((midiNote.roundToInt() % 12) + 12) % 12
                chromagram[pitchClass] += magnitudes[bin]
            }
        }

        // Normalize
        val maxVal = chromagram.max()
        if (maxVal > 0) {
            for (i in chromagram.indices) chromagram[i] /= maxVal
        }

        // Match against key profiles (Krumhansl-Kessler)
        var bestKey = "C major"
        var bestCorrelation = Double.NEGATIVE_INFINITY

        for (root in 0..11) {
            // Rotate profile to match root
            val majorCorr = correlate(chromagram, rotate(MAJOR_PROFILE, root))
            val minorCorr = correlate(chromagram, rotate(MINOR_PROFILE, root))

            if (majorCorr > bestCorrelation) {
                bestCorrelation = majorCorr
                bestKey = "${NOTE_NAMES[root]} major"
            }
            if (minorCorr > bestCorrelation) {
                bestCorrelation = minorCorr
                bestKey = "${NOTE_NAMES[root]} minor"
            }
        }

        return bestKey
    }

    /**
     * Simple radix-2 FFT returning magnitude spectrum.
     */
    private fun computeFFTMagnitudes(input: FloatArray): DoubleArray {
        val n = input.size
        // Ensure power of 2
        val real = DoubleArray(n) { input[it].toDouble() }
        val imag = DoubleArray(n)

        // Bit-reversal permutation
        var j = 0
        for (i in 0 until n) {
            if (i < j) {
                val tempR = real[i]; real[i] = real[j]; real[j] = tempR
                val tempI = imag[i]; imag[i] = imag[j]; imag[j] = tempI
            }
            var m = n / 2
            while (m >= 1 && j >= m) {
                j -= m
                m /= 2
            }
            j += m
        }

        // Cooley-Tukey FFT
        var step = 1
        while (step < n) {
            val halfStep = step
            step *= 2
            val angle = -PI / halfStep
            val wR = cos(angle)
            val wI = sin(angle)
            for (k in 0 until n step step) {
                var uR = 1.0
                var uI = 0.0
                for (m2 in 0 until halfStep) {
                    val t = k + m2
                    val tPlusHalf = t + halfStep
                    val tR = uR * real[tPlusHalf] - uI * imag[tPlusHalf]
                    val tI = uR * imag[tPlusHalf] + uI * real[tPlusHalf]
                    real[tPlusHalf] = real[t] - tR
                    imag[tPlusHalf] = imag[t] - tI
                    real[t] += tR
                    imag[t] += tI
                    val newUR = uR * wR - uI * wI
                    uI = uR * wI + uI * wR
                    uR = newUR
                }
            }
        }

        // Return magnitudes for first half (positive frequencies)
        return DoubleArray(n / 2) { i -> sqrt(real[i] * real[i] + imag[i] * imag[i]) }
    }

    private fun rotate(profile: DoubleArray, shift: Int): DoubleArray {
        val n = profile.size
        return DoubleArray(n) { i -> profile[(i - shift + n) % n] }
    }

    private fun correlate(a: DoubleArray, b: DoubleArray): Double {
        val meanA = a.average()
        val meanB = b.average()
        var num = 0.0
        var denA = 0.0
        var denB = 0.0
        for (i in a.indices) {
            val da = a[i] - meanA
            val db = b[i] - meanB
            num += da * db
            denA += da * da
            denB += db * db
        }
        val den = sqrt(denA * denB)
        return if (den > 0) num / den else 0.0
    }
}
