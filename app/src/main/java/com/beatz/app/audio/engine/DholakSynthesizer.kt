package com.beatz.app.audio.engine

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

/**
 * Synthesizes dholak/tabla-style percussion sounds and rhythm patterns.
 * Uses additive synthesis with noise components for realistic Indian percussion.
 */
object DholakSynthesizer {

    private const val SAMPLE_RATE = 44100

    /**
     * Dholak "ge" (bass hit) — deep, resonant low thump.
     */
    fun ge(velocity: Float = 0.8f): FloatArray {
        val duration = (SAMPLE_RATE * 0.4).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            // Higher pitch range so phone speakers can reproduce it
            val freq = 150.0 + 80.0 * exp(-12.0 * t)
            val env = exp(-4.0 * t) * velocity

            val fundamental = sin(2 * PI * freq * t) * 0.7
            val h2 = sin(2 * PI * freq * 2.0 * t) * exp(-6.0 * t) * 0.5
            val h3 = sin(2 * PI * freq * 3.0 * t) * exp(-8.0 * t) * 0.3
            val h4 = sin(2 * PI * freq * 4.0 * t) * exp(-12.0 * t) * 0.15

            // Punchy attack noise
            val noiseEnv = exp(-40.0 * t)
            val noise = (Random.nextFloat() * 2f - 1f) * noiseEnv * 0.4

            ((fundamental + h2 + h3 + h4) * env + noise).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Dholak "na" (treble slap) — sharp, high-pitched crack.
     */
    fun na(velocity: Float = 0.7f): FloatArray {
        val duration = (SAMPLE_RATE * 0.2).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val env = exp(-15.0 * t) * velocity

            // Higher pitched with quick decay — boosted
            val f1 = sin(2 * PI * 350.0 * t) * 0.7
            val f2 = sin(2 * PI * 520.0 * t) * exp(-18.0 * t) * 0.5
            val f3 = sin(2 * PI * 800.0 * t) * exp(-25.0 * t) * 0.35
            val f4 = sin(2 * PI * 1200.0 * t) * exp(-35.0 * t) * 0.2

            // Sharp attack noise
            val noiseEnv = exp(-60.0 * t)
            val noise = (Random.nextFloat() * 2f - 1f) * noiseEnv * 0.5

            ((f1 + f2 + f3 + f4) * env + noise).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Dholak "dhin" (combined bass + treble) — full open hit.
     */
    fun dhin(velocity: Float = 0.85f): FloatArray {
        val geSound = ge(velocity * 0.7f)
        val naSound = na(velocity * 0.5f)
        val length = maxOf(geSound.size, naSound.size)
        return FloatArray(length) { i ->
            val g = if (i < geSound.size) geSound[i] else 0f
            val n = if (i < naSound.size) naSound[i] else 0f
            (g + n).coerceIn(-1f, 1f)
        }
    }

    /**
     * Light ghost tap — very soft filler note.
     */
    fun ghost(velocity: Float = 0.35f): FloatArray {
        val duration = (SAMPLE_RATE * 0.1).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val env = exp(-40.0 * t) * velocity
            val tone = sin(2 * PI * 400.0 * t) * 0.5
            val noise = (Random.nextFloat() * 2f - 1f) * exp(-50.0 * t) * 0.5
            ((tone + noise) * env).toFloat()
        }
    }

    /**
     * Rhythm pattern: describes which sound to play at each subdivision.
     * Each entry is (beatOffset in beats, sound name, velocity).
     */
    data class Hit(val beatOffset: Float, val sound: String, val velocity: Float)

    /** Keherwa — 8-beat Bollywood staple (4/4 time) */
    val KEHERWA = listOf(
        Hit(0.0f, "dhin", 0.9f),
        Hit(0.5f, "ghost", 0.2f),
        Hit(1.0f, "na", 0.6f),
        Hit(1.5f, "ghost", 0.2f),
        Hit(2.0f, "dhin", 0.7f),
        Hit(2.5f, "na", 0.4f),
        Hit(3.0f, "na", 0.65f),
        Hit(3.5f, "ghost", 0.25f),
    )

    /** Dadra — 6-beat pattern (3/4 feel, mapped to 4/4) */
    val DADRA = listOf(
        Hit(0.0f, "dhin", 0.9f),
        Hit(0.75f, "na", 0.4f),
        Hit(1.0f, "ghost", 0.2f),
        Hit(1.5f, "na", 0.5f),
        Hit(2.0f, "ge", 0.7f),
        Hit(2.5f, "ghost", 0.2f),
        Hit(3.0f, "na", 0.6f),
        Hit(3.5f, "na", 0.35f),
    )

    /** Bhangra — energetic Punjabi pattern */
    val BHANGRA = listOf(
        Hit(0.0f, "dhin", 1.0f),
        Hit(0.25f, "ghost", 0.3f),
        Hit(0.5f, "na", 0.7f),
        Hit(1.0f, "ge", 0.8f),
        Hit(1.5f, "na", 0.6f),
        Hit(1.75f, "ghost", 0.3f),
        Hit(2.0f, "dhin", 0.9f),
        Hit(2.5f, "na", 0.65f),
        Hit(2.75f, "ghost", 0.25f),
        Hit(3.0f, "ge", 0.75f),
        Hit(3.5f, "na", 0.7f),
        Hit(3.75f, "na", 0.4f),
    )

    fun getPatterns(): Map<String, List<Hit>> = mapOf(
        "Keherwa" to KEHERWA,
        "Dadra" to DADRA,
        "Bhangra" to BHANGRA,
    )

    /**
     * Generate a sound sample by name.
     */
    fun generateHit(name: String, velocity: Float): FloatArray = when (name) {
        "ge" -> ge(velocity)
        "na" -> na(velocity)
        "dhin" -> dhin(velocity)
        "ghost" -> ghost(velocity)
        else -> ghost(velocity)
    }
}
