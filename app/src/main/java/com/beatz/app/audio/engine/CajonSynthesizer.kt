package com.beatz.app.audio.engine

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin
import kotlin.random.Random

/**
 * Synthesizes cajon (box drum) percussion sounds and rhythm patterns.
 */
object CajonSynthesizer {

    private const val SAMPLE_RATE = 44100

    /**
     * Bass tone — deep thump, hand in center of cajon.
     */
    fun bass(velocity: Float = 0.9f): FloatArray {
        val duration = (SAMPLE_RATE * 0.35).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val freq = 55.0 + 30.0 * exp(-20.0 * t)
            val env = exp(-6.0 * t) * velocity

            val fundamental = sin(2 * PI * freq * t) * 0.7
            val h2 = sin(2 * PI * freq * 2.0 * t) * exp(-10.0 * t) * 0.2
            // Box resonance
            val box = sin(2 * PI * 120.0 * t) * exp(-8.0 * t) * 0.15

            // Thump noise
            val noiseEnv = exp(-40.0 * t)
            val noise = (Random.nextFloat() * 2f - 1f) * noiseEnv * 0.2

            ((fundamental + h2 + box) * env + noise).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Slap — sharp crack at the edge of the cajon.
     */
    fun slap(velocity: Float = 0.8f): FloatArray {
        val duration = (SAMPLE_RATE * 0.15).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val env = exp(-25.0 * t) * velocity

            // High frequency crack
            val f1 = sin(2 * PI * 400.0 * t) * exp(-20.0 * t) * 0.3
            val f2 = sin(2 * PI * 700.0 * t) * exp(-30.0 * t) * 0.2
            val f3 = sin(2 * PI * 1100.0 * t) * exp(-40.0 * t) * 0.15

            // Snappy noise
            val noiseEnv = exp(-60.0 * t)
            val noise = (Random.nextFloat() * 2f - 1f) * noiseEnv * 0.5

            ((f1 + f2 + f3) * env + noise * velocity).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Ghost — light fingertip tap.
     */
    fun ghost(velocity: Float = 0.2f): FloatArray {
        val duration = (SAMPLE_RATE * 0.06).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SAMPLE_RATE
            val env = exp(-60.0 * t) * velocity
            val noise = (Random.nextFloat() * 2f - 1f)
            val tone = sin(2 * PI * 300.0 * t) * 0.2
            ((noise + tone) * env).toFloat()
        }
    }

    data class Hit(val beatOffset: Float, val sound: String, val velocity: Float)

    /** Pop/Rock — standard 4/4 groove */
    val POP_ROCK = listOf(
        Hit(0.0f, "bass", 0.9f),
        Hit(0.5f, "ghost", 0.2f),
        Hit(1.0f, "slap", 0.75f),
        Hit(1.5f, "ghost", 0.2f),
        Hit(2.0f, "bass", 0.8f),
        Hit(2.5f, "ghost", 0.25f),
        Hit(3.0f, "slap", 0.7f),
        Hit(3.5f, "ghost", 0.2f),
    )

    /** Ballad — gentle, spacious */
    val BALLAD = listOf(
        Hit(0.0f, "bass", 0.7f),
        Hit(1.0f, "ghost", 0.15f),
        Hit(2.0f, "slap", 0.5f),
        Hit(2.5f, "ghost", 0.15f),
        Hit(3.0f, "ghost", 0.2f),
        Hit(3.5f, "ghost", 0.15f),
    )

    /** Upbeat — driving rhythm */
    val UPBEAT = listOf(
        Hit(0.0f, "bass", 1.0f),
        Hit(0.5f, "slap", 0.4f),
        Hit(1.0f, "slap", 0.8f),
        Hit(1.5f, "ghost", 0.3f),
        Hit(2.0f, "bass", 0.9f),
        Hit(2.5f, "slap", 0.4f),
        Hit(3.0f, "slap", 0.75f),
        Hit(3.25f, "ghost", 0.2f),
        Hit(3.5f, "slap", 0.5f),
    )

    fun getPatterns(): Map<String, List<Hit>> = mapOf(
        "Pop/Rock" to POP_ROCK,
        "Ballad" to BALLAD,
        "Upbeat" to UPBEAT,
    )

    fun generateHit(name: String, velocity: Float): FloatArray = when (name) {
        "bass" -> bass(velocity)
        "slap" -> slap(velocity)
        "ghost" -> ghost(velocity)
        else -> ghost(velocity)
    }
}
