package com.beatz.app.audio.analysis

import com.beatz.app.audio.decoder.DecodedAudio
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * Detects tempo (BPM) from decoded audio using energy-based onset detection
 * and autocorrelation of the onset signal. Pure Kotlin — no external libraries.
 */
object TempoDetector {

    fun detectBpm(audio: DecodedAudio): Float {
        val sampleRate = audio.sampleRate
        val maxSamples = sampleRate * 20
        val rawMono = mixToMono(audio.samples, audio.channels)
        val mono = if (rawMono.size > maxSamples) rawMono.copyOf(maxSamples) else rawMono

        // Compute energy envelope using smaller windows for better resolution
        val windowSize = sampleRate / 20  // 50ms windows
        val hopSize = windowSize / 4      // 12.5ms hop
        val envelope = computeEnergyEnvelope(mono, windowSize, hopSize)
        if (envelope.size < 10) return 120f

        // Compute onset strength signal (half-wave rectified first difference)
        val onsetSignal = FloatArray(envelope.size - 1)
        for (i in onsetSignal.indices) {
            onsetSignal[i] = maxOf(0f, envelope[i + 1] - envelope[i])
        }

        // Autocorrelation of onset signal to find periodicity
        val hopDurationSec = hopSize.toDouble() / sampleRate
        val minBpm = 60f
        val maxBpm = 200f
        val minLag = (60.0 / maxBpm / hopDurationSec).toInt()
        val maxLag = (60.0 / minBpm / hopDurationSec).toInt().coerceAtMost(onsetSignal.size / 2)

        if (minLag >= maxLag) return 120f

        // Compute autocorrelation for each lag
        val correlations = FloatArray(maxLag + 1)
        for (lag in minLag..maxLag) {
            var sum = 0.0
            var count = 0
            for (i in 0 until onsetSignal.size - lag) {
                sum += onsetSignal[i].toDouble() * onsetSignal[i + lag].toDouble()
                count++
            }
            correlations[lag] = if (count > 0) (sum / count).toFloat() else 0f
        }

        // Find the strongest peak in the autocorrelation
        // Weight towards common BPM ranges (80-160) with a gentle bias
        var bestLag = minLag
        var bestScore = 0f
        for (lag in minLag..maxLag) {
            val bpmAtLag = 60.0 / (lag * hopDurationSec)
            // Gentle preference for typical BPM range (80-160)
            val weight = if (bpmAtLag in 80.0..160.0) 1.1f else 1.0f
            val score = correlations[lag] * weight
            if (score > bestScore) {
                bestScore = score
                bestLag = lag
            }
        }

        val detectedBpm = (60.0 / (bestLag * hopDurationSec)).toFloat()

        // Octave correction: if BPM > 160, check if half-tempo has strong correlation too
        // Most music is 80-160 BPM, so prefer half-tempo when it's plausible
        val finalBpm = when {
            detectedBpm > 160f -> {
                val halfLag = bestLag * 2
                if (halfLag <= maxLag && correlations[halfLag] > bestScore * 0.5f) {
                    detectedBpm / 2  // Half-tempo has decent support
                } else {
                    detectedBpm / 2  // Still prefer half for very high BPM
                }
            }
            detectedBpm < 75f -> {
                val doubleBpm = detectedBpm * 2
                if (doubleBpm in 60f..200f) doubleBpm else detectedBpm
            }
            else -> detectedBpm
        }

        return finalBpm.coerceIn(60f, 200f)
    }

    private fun mixToMono(samples: FloatArray, channels: Int): FloatArray {
        if (channels == 1) return samples
        val mono = FloatArray(samples.size / channels)
        for (i in mono.indices) {
            var sum = 0f
            for (ch in 0 until channels) {
                sum += samples[i * channels + ch]
            }
            mono[i] = sum / channels
        }
        return mono
    }

    private fun computeEnergyEnvelope(
        samples: FloatArray,
        windowSize: Int,
        hopSize: Int
    ): FloatArray {
        val numFrames = (samples.size - windowSize) / hopSize + 1
        if (numFrames <= 0) return floatArrayOf()
        val envelope = FloatArray(numFrames)
        for (i in 0 until numFrames) {
            val start = i * hopSize
            var energy = 0f
            for (j in 0 until windowSize) {
                if (start + j < samples.size) {
                    val s = samples[start + j]
                    energy += s * s
                }
            }
            envelope[i] = energy / windowSize
        }
        return envelope
    }
}
