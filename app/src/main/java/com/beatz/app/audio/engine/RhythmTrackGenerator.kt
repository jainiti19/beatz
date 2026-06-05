package com.beatz.app.audio.engine

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs

/**
 * Generates rhythm backing tracks (dholak or cajon) from BPM.
 * Outputs a WAV file that can be added as a stem in StemPlayer.
 */
object RhythmTrackGenerator {

    private const val SAMPLE_RATE = 44100

    enum class Instrument { DHOLAK, CAJON }

    /**
     * Generate a rhythm track WAV.
     * @param bpm tempo
     * @param totalDurationSeconds length of track
     * @param instrument DHOLAK or CAJON
     * @param patternName which rhythm pattern to use
     * @param outputFile where to write the WAV
     */
    fun generate(
        bpm: Float,
        totalDurationSeconds: Float,
        instrument: Instrument,
        patternName: String,
        outputFile: File
    ): Boolean {
        val totalSamples = (totalDurationSeconds * SAMPLE_RATE).toInt()
        val output = FloatArray(totalSamples)
        val beatDuration = 60f / bpm
        val barDuration = beatDuration * 4

        // Convert pattern to common triple format: (beatOffset, soundName, velocity)
        data class RhythmHit(val beatOffset: Float, val sound: String, val velocity: Float)

        val pattern: List<RhythmHit> = when (instrument) {
            Instrument.DHOLAK -> (DholakSynthesizer.getPatterns()[patternName]
                ?: DholakSynthesizer.KEHERWA).map { RhythmHit(it.beatOffset, it.sound, it.velocity) }
            Instrument.CAJON -> (CajonSynthesizer.getPatterns()[patternName]
                ?: CajonSynthesizer.POP_ROCK).map { RhythmHit(it.beatOffset, it.sound, it.velocity) }
        }

        // Place pattern hits across the full duration, one bar at a time
        var barStart = 0f
        while (barStart < totalDurationSeconds) {
            for (hit in pattern) {
                val hitTime = barStart + hit.beatOffset * beatDuration
                if (hitTime >= totalDurationSeconds) break

                val hitSample = (hitTime * SAMPLE_RATE).toInt()
                if (hitSample >= totalSamples) continue

                // Add slight humanization: ±5ms timing jitter
                val jitter = ((kotlin.random.Random.nextFloat() - 0.5f) * 0.01f * SAMPLE_RATE).toInt()
                val offset = (hitSample + jitter).coerceIn(0, totalSamples - 1)

                // Slight velocity variation for natural feel
                val velVariation = hit.velocity * (0.9f + kotlin.random.Random.nextFloat() * 0.1f)

                val sound = when (instrument) {
                    Instrument.DHOLAK -> DholakSynthesizer.generateHit(hit.sound, velVariation)
                    Instrument.CAJON -> CajonSynthesizer.generateHit(hit.sound, velVariation)
                }

                for (i in sound.indices) {
                    val outIdx = offset + i
                    if (outIdx < totalSamples) {
                        output[outIdx] += sound[i]
                    }
                }
            }
            barStart += barDuration
        }

        // Normalize to near-max volume
        val peak = output.maxOfOrNull { abs(it) } ?: 1f
        if (peak > 0.01f) {
            val scale = 0.95f / peak
            for (i in output.indices) output[i] *= scale
        }

        return writeWav(output, outputFile)
    }

    private fun writeWav(samples: FloatArray, file: File): Boolean {
        try {
            file.parentFile?.mkdirs()
            RandomAccessFile(file, "rw").use { raf ->
                // Write as stereo 16-bit to match Demucs stems
                val channels = 2
                val dataSize = samples.size * channels * 2
                val fileSize = 44 + dataSize

                val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
                header.put("RIFF".toByteArray())
                header.putInt(fileSize - 8)
                header.put("WAVE".toByteArray())
                header.put("fmt ".toByteArray())
                header.putInt(16)
                header.putShort(1)
                header.putShort(channels.toShort())
                header.putInt(SAMPLE_RATE)
                header.putInt(SAMPLE_RATE * channels * 2)
                header.putShort((channels * 2).toShort())
                header.putShort(16)
                header.put("data".toByteArray())
                header.putInt(dataSize)
                raf.write(header.array())

                val chunkSize = 4096
                val buf = ByteBuffer.allocate(chunkSize * channels * 2).order(ByteOrder.LITTLE_ENDIAN)
                var offset = 0
                while (offset < samples.size) {
                    buf.clear()
                    val end = minOf(offset + chunkSize, samples.size)
                    for (i in offset until end) {
                        val s = (samples[i] * 32767f).toInt().coerceIn(-32768, 32767).toShort()
                        buf.putShort(s) // Left
                        buf.putShort(s) // Right
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
