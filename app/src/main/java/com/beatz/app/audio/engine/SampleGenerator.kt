package com.beatz.app.audio.engine

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

/**
 * Generates synthetic audio samples programmatically.
 * Supports both fixed percussion samples and dynamically pitched
 * melodic samples for piano, guitar, and flute.
 */
object SampleGenerator {

    private const val SAMPLE_RATE = 44100

    /**
     * Generate all fixed (non-pitched) samples.
     */
    fun generateAllSamples(): Map<String, FloatArray> {
        return mutableMapOf(
            // Drums
            "kick" to generateKick(),
            "snare" to generateSnare(),
            "hihat" to generateHiHat(),

            // Tabla
            "dha" to generateDha(),
            "tin" to generateTin()
        )
    }

    /**
     * Generate a pitched piano sample for a specific MIDI note.
     * Sample name format: "piano_60" for middle C.
     */
    fun generatePianoNote(midiNote: Int): FloatArray {
        val freq = midiToFrequency(midiNote)
        val durationSamples = (SAMPLE_RATE * 0.5).toInt()
        return FloatArray(durationSamples) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val envelope = exp(-3.0 * t)
            val sample = sin(2 * PI * freq * t) * envelope * 0.5 +
                    sin(2 * PI * freq * 2 * t) * envelope * 0.2 +
                    sin(2 * PI * freq * 3 * t) * envelope * 0.1 +
                    sin(2 * PI * freq * 4 * t) * envelope * 0.05
            sample.toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Generate a pitched guitar sample for a specific MIDI note.
     * Uses Karplus-Strong-like plucked string synthesis.
     */
    fun generateGuitarNote(midiNote: Int): FloatArray {
        val freq = midiToFrequency(midiNote)
        val durationSamples = (SAMPLE_RATE * 0.5).toInt()
        val period = (SAMPLE_RATE / freq).toInt().coerceAtLeast(2)

        // Initialize with noise burst (pluck excitation)
        val buffer = FloatArray(durationSamples)
        for (i in 0 until period) {
            buffer[i] = Random.nextFloat() * 2 - 1
        }

        // Karplus-Strong: average adjacent samples with decay
        for (i in period until durationSamples) {
            buffer[i] = (buffer[i - period] + buffer[i - period + 1]) * 0.498f
        }

        // Apply gentle envelope to avoid clicks
        val fadeOut = (SAMPLE_RATE * 0.02).toInt()
        for (i in maxOf(0, durationSamples - fadeOut) until durationSamples) {
            val fade = (durationSamples - i).toFloat() / fadeOut
            buffer[i] *= fade
        }

        return buffer
    }

    /**
     * Generate a pitched flute sample for a specific MIDI note.
     * Pure tone with vibrato and breath noise.
     */
    fun generateFluteNote(midiNote: Int, longNote: Boolean = true): FloatArray {
        val freq = midiToFrequency(midiNote)
        val durationMs = if (longNote) 400 else 150
        val durationSamples = (SAMPLE_RATE * durationMs / 1000.0).toInt()
        return FloatArray(durationSamples) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val attack = minOf(t / 0.02, 1.0)
            val release = minOf((durationMs / 1000.0 - t) / 0.05, 1.0).coerceAtLeast(0.0)
            val envelope = attack * release
            val vibrato = 1.0 + 0.005 * sin(2 * PI * 5.5 * t)
            val sample = sin(2 * PI * freq * vibrato * t) * envelope
            val noise = (Random.nextFloat() * 2 - 1) * 0.03 * envelope
            (sample + noise).toFloat().coerceIn(-1f, 1f)
        }
    }

    private fun midiToFrequency(midiNote: Int): Double {
        return 440.0 * 2.0.pow((midiNote - 69) / 12.0)
    }

    /** Kick drum: low sine wave with fast exponential decay */
    private fun generateKick(): FloatArray {
        val durationSamples = (SAMPLE_RATE * 0.3).toInt()
        return FloatArray(durationSamples) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val freq = 60.0 + 80.0 * exp(-30.0 * t)
            val envelope = exp(-8.0 * t)
            (sin(2 * PI * freq * t) * envelope).toFloat().coerceIn(-1f, 1f)
        }
    }

    /** Snare: mix of tone + noise with medium decay */
    private fun generateSnare(): FloatArray {
        val durationSamples = (SAMPLE_RATE * 0.2).toInt()
        return FloatArray(durationSamples) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val tone = sin(2 * PI * 200.0 * t) * exp(-20.0 * t)
            val noise = (Random.nextFloat() * 2 - 1) * exp(-12.0 * t)
            (tone * 0.4 + noise * 0.6).toFloat().coerceIn(-1f, 1f)
        }
    }

    /** Hi-hat: filtered noise with very fast decay */
    private fun generateHiHat(): FloatArray {
        val durationSamples = (SAMPLE_RATE * 0.08).toInt()
        return FloatArray(durationSamples) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val noise = (Random.nextFloat() * 2 - 1)
            val envelope = exp(-40.0 * t)
            (noise * envelope * 0.5).toFloat()
        }
    }

    /** Tabla dha: low resonant tone */
    private fun generateDha(): FloatArray {
        val durationSamples = (SAMPLE_RATE * 0.35).toInt()
        return FloatArray(durationSamples) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val f1 = sin(2 * PI * 100.0 * t) * exp(-6.0 * t)
            val f2 = sin(2 * PI * 150.0 * t) * exp(-8.0 * t)
            val f3 = sin(2 * PI * 250.0 * t) * exp(-12.0 * t)
            (f1 * 0.5 + f2 * 0.3 + f3 * 0.2).toFloat().coerceIn(-1f, 1f)
        }
    }

    /** Tabla tin: higher pitched, shorter */
    private fun generateTin(): FloatArray {
        val durationSamples = (SAMPLE_RATE * 0.15).toInt()
        return FloatArray(durationSamples) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val f1 = sin(2 * PI * 400.0 * t) * exp(-15.0 * t)
            val f2 = sin(2 * PI * 800.0 * t) * exp(-20.0 * t)
            val f3 = sin(2 * PI * 1200.0 * t) * exp(-25.0 * t)
            (f1 * 0.4 + f2 * 0.35 + f3 * 0.25).toFloat().coerceIn(-1f, 1f)
        }
    }
}
