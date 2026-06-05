package com.beatz.app.audio.engine

import com.beatz.app.audio.analysis.ChordSegment
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Generates a guitar backing track WAV from a chord timeline and BPM.
 * The guitar strums chords following the detected progression.
 */
object JammingTrackGenerator {

    private const val SAMPLE_RATE = 44100

    /**
     * Generate a guitar backing track WAV file.
     * @param chords detected chord progression
     * @param bpm tempo (used for strum pattern timing)
     * @param totalDurationSeconds total length to generate
     * @param patternName strum pattern to use ("Ballad", "Folk", "Bollywood")
     * @param outputFile where to save the WAV
     * @return true if successful
     */
    fun generateGuitarTrack(
        chords: List<ChordSegment>,
        bpm: Float,
        totalDurationSeconds: Float,
        patternName: String = "Bollywood",
        outputFile: File
    ): Boolean {
        if (chords.isEmpty()) return false

        val totalSamples = (totalDurationSeconds * SAMPLE_RATE).toInt()
        val output = FloatArray(totalSamples)

        val beatDurationSec = 60f / bpm
        val pattern = GuitarSynthesizer.getPatterns()[patternName]
            ?: GuitarSynthesizer.PATTERN_BOLLYWOOD

        // For each chord segment, place strums according to the pattern
        for (seg in chords) {
            if (seg.chord == "N/C") continue

            val segStartSample = (seg.startTime * SAMPLE_RATE).toInt()
            val segEndSample = (seg.endTime * SAMPLE_RATE).toInt().coerceAtMost(totalSamples)
            val segDuration = seg.endTime - seg.startTime

            // Place strum pattern within this segment, repeating every 4 beats (1 bar)
            val barDuration = beatDurationSec * 4
            var barStart = seg.startTime

            while (barStart < seg.endTime) {
                for (hit in pattern) {
                    val hitTime = barStart + hit.beatOffset * beatDurationSec
                    if (hitTime < seg.startTime || hitTime >= seg.endTime) continue

                    val hitSample = (hitTime * SAMPLE_RATE).toInt()
                    if (hitSample >= totalSamples) continue

                    // Ring duration: until next hit or end of segment, max 2 seconds
                    val ringDuration = minOf(
                        2.0f,
                        seg.endTime - hitTime,
                        barDuration
                    )

                    val strum = GuitarSynthesizer.synthesizeStrum(
                        chordName = seg.chord,
                        isDown = hit.isDown,
                        velocity = hit.velocity,
                        durationSeconds = ringDuration
                    )

                    // Mix into output
                    for (i in strum.indices) {
                        val outIdx = hitSample + i
                        if (outIdx < totalSamples) {
                            output[outIdx] += strum[i]
                        }
                    }
                }
                barStart += barDuration
            }
        }

        // Normalize to prevent clipping
        val peak = output.maxOfOrNull { kotlin.math.abs(it) } ?: 1f
        if (peak > 0.9f) {
            val scale = 0.85f / peak
            for (i in output.indices) output[i] *= scale
        }

        // Write WAV
        return writeWav(output, outputFile)
    }

    /**
     * Write mono PCM float samples to a 16-bit WAV file.
     */
    private fun writeWav(samples: FloatArray, file: File): Boolean {
        try {
            file.parentFile?.mkdirs()
            RandomAccessFile(file, "rw").use { raf ->
                val numSamples = samples.size
                val dataSize = numSamples * 2  // 16-bit = 2 bytes per sample
                val fileSize = 44 + dataSize

                // WAV header
                val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
                header.put("RIFF".toByteArray())
                header.putInt(fileSize - 8)
                header.put("WAVE".toByteArray())
                header.put("fmt ".toByteArray())
                header.putInt(16)           // chunk size
                header.putShort(1)          // PCM format
                header.putShort(1)          // mono
                header.putInt(SAMPLE_RATE)
                header.putInt(SAMPLE_RATE * 2)  // byte rate
                header.putShort(2)          // block align
                header.putShort(16)         // bits per sample
                header.put("data".toByteArray())
                header.putInt(dataSize)

                raf.write(header.array())

                // Write PCM data in chunks
                val chunkSize = 8192
                val buf = ByteBuffer.allocate(chunkSize * 2).order(ByteOrder.LITTLE_ENDIAN)
                var offset = 0

                while (offset < numSamples) {
                    buf.clear()
                    val end = minOf(offset + chunkSize, numSamples)
                    for (i in offset until end) {
                        val s = (samples[i] * 32767f).toInt().coerceIn(-32768, 32767).toShort()
                        buf.putShort(s)
                    }
                    buf.flip()
                    val bytes = ByteArray(buf.remaining())
                    buf.get(bytes)
                    raf.write(bytes)
                    offset = end
                }
            }
            return true
        } catch (e: Exception) {
            e.printStackTrace()
            return false
        }
    }
}
