package com.beatz.app.audio.engine

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.random.Random

/**
 * Indian Taal (rhythm cycle) system.
 *
 * Each Taal has:
 * - beats: total beats in the cycle
 * - vibhag: divisions of the cycle
 * - sam: beat 1 (accented, clap)
 * - khali: the empty beat (wave)
 * - theka: the fixed pattern of bols
 */
data class Taal(
    val name: String,
    val displayName: String,
    val beats: Int,
    val theka: List<String>,     // One bol per beat
    val samBeats: List<Int>,     // Beat numbers that get Sam accent (1-indexed)
    val khaliBeats: List<Int>,   // Beat numbers that are Khali
    val description: String
)

object TaalSystem {

    /**
     * Keherwa - 8 beats (2 vibhag of 4)
     * Most common in Bollywood, film songs, light music
     * | Dha Ge Na Ti | Na Ke Dhi Na |
     */
    val KEHERWA = Taal(
        name = "keherwa",
        displayName = "Keherwa",
        beats = 8,
        theka = listOf("Dha", "Ge", "Na", "Ti", "Na", "Ke", "Dhin", "Na"),
        samBeats = listOf(1),
        khaliBeats = listOf(5),
        description = "8 beats • Bollywood & film songs"
    )

    /**
     * Dadra - 6 beats (2 vibhag of 3)
     * Used in light classical, romantic songs, folk
     * | Dha Dhin Na | Na Tin Na |
     */
    val DADRA = Taal(
        name = "dadra",
        displayName = "Dadra",
        beats = 6,
        theka = listOf("Dha", "Dhin", "Na", "Na", "Tin", "Na"),
        samBeats = listOf(1),
        khaliBeats = listOf(4),
        description = "6 beats • Romantic & folk songs"
    )

    /**
     * Teentaal - 16 beats (4 vibhag of 4)
     * Most important taal in Indian classical music
     * | Dha Dhin Dhin Dha | Dha Dhin Dhin Dha | Na Tin Tin Na | Na Dhin Dhin Dha |
     */
    val TEENTAAL = Taal(
        name = "teentaal",
        displayName = "Teentaal",
        beats = 16,
        theka = listOf(
            "Dha", "Dhin", "Dhin", "Dha",
            "Dha", "Dhin", "Dhin", "Dha",
            "Na", "Tin", "Tin", "Na",
            "Na", "Dhin", "Dhin", "Dha"
        ),
        samBeats = listOf(1),
        khaliBeats = listOf(9),
        description = "16 beats • Classical & versatile"
    )

    /**
     * Rupak - 7 beats (3 vibhag: 3+2+2)
     * Unique because Sam is also Khali (starts with wave)
     * | Tin Tin Na | Dhin Na | Dhin Na |
     */
    val RUPAK = Taal(
        name = "rupak",
        displayName = "Rupak",
        beats = 7,
        theka = listOf("Tin", "Tin", "Na", "Dhin", "Na", "Dhin", "Na"),
        samBeats = listOf(1),
        khaliBeats = listOf(1),
        description = "7 beats • Melodic & thoughtful"
    )

    /**
     * Jhaptaal - 10 beats (4 vibhag: 2+3+2+3)
     * Medium tempo classical compositions
     * | Dhin Na | Dhin Dhin Na | Tin Na | Dhin Dhin Na |
     */
    val JHAPTAAL = Taal(
        name = "jhaptaal",
        displayName = "Jhaptaal",
        beats = 10,
        theka = listOf("Dhin", "Na", "Dhin", "Dhin", "Na", "Tin", "Na", "Dhin", "Dhin", "Na"),
        samBeats = listOf(1),
        khaliBeats = listOf(6),
        description = "10 beats • Classical medium tempo"
    )

    val ALL_TAALS = listOf(KEHERWA, DADRA, TEENTAAL, RUPAK, JHAPTAAL)

    /**
     * Generate a full taal track as a stereo WAV.
     */
    fun generateTrack(
        taal: Taal,
        bpm: Float,
        totalDurationSeconds: Float,
        outputFile: File
    ): Boolean {
        val sampleRate = 44100
        val totalSamples = (totalDurationSeconds * sampleRate).toInt()
        val output = FloatArray(totalSamples)

        val beatDuration = 60f / bpm
        val cycleDuration = beatDuration * taal.beats

        var cycleStart = 0f
        var cycleNumber = 0

        while (cycleStart < totalDurationSeconds) {
            cycleNumber++

            for (beatIndex in taal.theka.indices) {
                val bol = taal.theka[beatIndex]
                val beatNum = beatIndex + 1
                val beatTime = cycleStart + beatIndex * beatDuration

                if (beatTime >= totalDurationSeconds) break

                val beatSample = (beatTime * sampleRate).toInt()
                if (beatSample >= totalSamples) break

                // Velocity: Sam gets accent, Khali is softer
                var vel = 0.75f
                if (beatNum in taal.samBeats) vel = 1.0f      // Sam — strong accent
                if (beatNum in taal.khaliBeats && beatNum !in taal.samBeats) vel = 0.55f  // Khali — lighter

                // Humanization
                vel *= (0.88f + Random.nextFloat() * 0.12f)
                val jitter = ((Random.nextFloat() - 0.5f) * 0.006f * sampleRate).toInt()
                val offset = (beatSample + jitter).coerceIn(0, totalSamples - 1)

                // Every 4 cycles, add slight variation
                if (cycleNumber % 4 == 0 && beatIndex == taal.beats - 1) {
                    // Fill on last beat of every 4th cycle
                    val fillSound = TablaSynthesizer.playBol("Na", vel * 0.6f)
                    val fillOffset = offset - (beatDuration * 0.5f * sampleRate).toInt()
                    if (fillOffset > 0) {
                        for (i in fillSound.indices) {
                            val idx = fillOffset + i
                            if (idx in output.indices) output[idx] += fillSound[i]
                        }
                    }
                }

                // Generate the bol
                val sound = TablaSynthesizer.playBol(bol, vel)
                for (i in sound.indices) {
                    val idx = offset + i
                    if (idx < totalSamples) output[idx] += sound[i]
                }
            }

            cycleStart += cycleDuration
        }

        // Normalize
        val peak = output.maxOfOrNull { abs(it) } ?: 1f
        if (peak > 0.01f) {
            val scale = 0.95f / peak
            for (i in output.indices) output[i] *= scale
        }

        return writeWavStereo(output, outputFile, sampleRate)
    }

    private fun writeWavStereo(samples: FloatArray, file: File, sampleRate: Int): Boolean {
        try {
            file.parentFile?.mkdirs()
            RandomAccessFile(file, "rw").use { raf ->
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
                header.putInt(sampleRate)
                header.putInt(sampleRate * channels * 2)
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
                        buf.putShort(s)
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
