package com.beatz.app.audio.analysis

import com.beatz.app.audio.decoder.DecodedAudio
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Detects tempo (BPM) from decoded audio using energy-based onset detection
 * and autocorrelation. Pure Kotlin — no external libraries needed.
 */
object TempoDetector {

    /**
     * Detect BPM from decoded audio.
     * @return estimated BPM (typically 60-200 range)
     */
    fun detectBpm(audio: DecodedAudio): Float {
        // Mix to mono if stereo, limit to first 20 seconds
        val maxSamples = audio.sampleRate * 20
        val rawMono = mixToMono(audio.samples, audio.channels)
        val mono = if (rawMono.size > maxSamples) rawMono.copyOf(maxSamples) else rawMono

        // Compute energy envelope using RMS in windows
        val windowSize = audio.sampleRate / 10  // 100ms windows
        val hopSize = windowSize / 2
        val envelope = computeEnergyEnvelope(mono, windowSize, hopSize)

        // Detect onsets (peaks in the energy difference)
        val onsets = detectOnsets(envelope)

        if (onsets.size < 2) {
            return 120f // Default if we can't detect
        }

        // Convert onset indices to time in seconds
        val hopDuration = hopSize.toDouble() / audio.sampleRate
        val onsetTimes = onsets.map { it * hopDuration }

        // Calculate intervals between successive onsets
        val intervals = mutableListOf<Double>()
        for (i in 1 until onsetTimes.size) {
            intervals.add(onsetTimes[i] - onsetTimes[i - 1])
        }

        // Use autocorrelation on the onset intervals to find the dominant period
        val bpm = estimateBpmFromIntervals(intervals)

        // Clamp to reasonable range
        return bpm.coerceIn(60f, 200f)
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

    private fun detectOnsets(envelope: FloatArray): List<Int> {
        if (envelope.size < 3) return emptyList()

        // Spectral flux: positive difference between consecutive frames
        val flux = FloatArray(envelope.size - 1)
        for (i in flux.indices) {
            flux[i] = maxOf(0f, envelope[i + 1] - envelope[i])
        }

        // Adaptive threshold: mean + 1.5 * stddev
        val mean = flux.average().toFloat()
        val variance = flux.map { (it - mean) * (it - mean) }.average().toFloat()
        val stddev = kotlin.math.sqrt(variance)
        val threshold = mean + 1.5f * stddev

        // Pick peaks above threshold with minimum distance
        val minDistFrames = 3 // Minimum ~150ms between onsets
        val onsets = mutableListOf<Int>()
        var lastOnset = -minDistFrames
        for (i in flux.indices) {
            if (flux[i] > threshold && (i - lastOnset) >= minDistFrames) {
                onsets.add(i)
                lastOnset = i
            }
        }
        return onsets
    }

    private fun estimateBpmFromIntervals(intervals: List<Double>): Float {
        if (intervals.isEmpty()) return 120f

        // Create a histogram of BPM values from intervals
        val bpmCounts = mutableMapOf<Int, Int>()
        for (interval in intervals) {
            if (interval <= 0) continue
            val bpm = (60.0 / interval).roundToInt()
            if (bpm in 60..200) {
                bpmCounts[bpm] = (bpmCounts[bpm] ?: 0) + 1
                // Also count half and double time
                val halfBpm = bpm / 2
                val doubleBpm = bpm * 2
                if (halfBpm in 60..200) {
                    bpmCounts[halfBpm] = (bpmCounts[halfBpm] ?: 0) + 1
                }
                if (doubleBpm in 60..200) {
                    bpmCounts[doubleBpm] = (bpmCounts[doubleBpm] ?: 0) + 1
                }
            }
        }

        if (bpmCounts.isEmpty()) return 120f

        // Find the BPM with the most votes, smoothed over ±2 BPM
        var bestBpm = 120
        var bestScore = 0
        for (bpm in 60..200) {
            val score = (-2..2).sumOf { bpmCounts.getOrDefault(bpm + it, 0) }
            if (score > bestScore) {
                bestScore = score
                bestBpm = bpm
            }
        }

        return bestBpm.toFloat()
    }
}
