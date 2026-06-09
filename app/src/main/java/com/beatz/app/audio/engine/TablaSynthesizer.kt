package com.beatz.app.audio.engine

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

/**
 * Synthesizes authentic tabla sounds using additive synthesis.
 * Each bol (syllable) has distinct tonal characteristics.
 *
 * Right hand (dayan - treble drum):
 *   Na, Ta, Tin, Ti, Te
 * Left hand (bayan - bass drum):
 *   Ge, Ke, Ghe
 * Combined (both hands):
 *   Dha (= Ge + Na), Dhin (= Ghe + Tin)
 */
object TablaSynthesizer {

    private const val SR = 44100

    /**
     * Na — sharp, ringing treble hit (open center of dayan)
     * Characteristic: sustained ring, clear pitch ~350-450Hz
     */
    fun na(velocity: Float = 0.8f): FloatArray {
        val duration = (SR * 0.35).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR
            val env = exp(-4.5 * t) * velocity

            // Primary resonance with harmonics (pitched drum)
            val f0 = 380.0
            val fundamental = sin(2 * PI * f0 * t) * 0.6
            val h2 = sin(2 * PI * f0 * 1.56 * t) * exp(-5.0 * t) * 0.35
            val h3 = sin(2 * PI * f0 * 2.14 * t) * exp(-7.0 * t) * 0.25
            val h4 = sin(2 * PI * f0 * 2.65 * t) * exp(-9.0 * t) * 0.15
            val h5 = sin(2 * PI * f0 * 3.2 * t) * exp(-12.0 * t) * 0.08

            // Attack transient
            val attack = (Random.nextFloat() * 2f - 1f) * exp(-80.0 * t) * 0.3

            ((fundamental + h2 + h3 + h4 + h5) * env + attack).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Tin/Ta — dry, short treble hit (edge of dayan)
     * Characteristic: short, less ring than Na
     */
    fun tin(velocity: Float = 0.7f): FloatArray {
        val duration = (SR * 0.2).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR
            val env = exp(-12.0 * t) * velocity

            val f0 = 420.0
            val fundamental = sin(2 * PI * f0 * t) * 0.5
            val h2 = sin(2 * PI * f0 * 1.5 * t) * exp(-15.0 * t) * 0.4
            val h3 = sin(2 * PI * f0 * 2.3 * t) * exp(-20.0 * t) * 0.25
            val h4 = sin(2 * PI * f0 * 3.1 * t) * exp(-25.0 * t) * 0.15

            val attack = (Random.nextFloat() * 2f - 1f) * exp(-60.0 * t) * 0.4

            ((fundamental + h2 + h3 + h4) * env + attack).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Ti — very light tap on dayan
     */
    fun ti(velocity: Float = 0.4f): FloatArray {
        val duration = (SR * 0.12).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR
            val env = exp(-25.0 * t) * velocity

            val f0 = 450.0
            val tone = sin(2 * PI * f0 * t) * 0.4 + sin(2 * PI * f0 * 1.6 * t) * 0.2
            val attack = (Random.nextFloat() * 2f - 1f) * exp(-70.0 * t) * 0.35

            ((tone) * env + attack).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Ge/Ghe — bass hit on bayan (left hand)
     * Characteristic: deep, resonant, pitch bends down
     */
    fun ge(velocity: Float = 0.85f): FloatArray {
        val duration = (SR * 0.45).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR
            // Pitch bends down (characteristic of bayan)
            val freq = 160.0 + 60.0 * exp(-8.0 * t)
            val env = exp(-3.5 * t) * velocity

            val fundamental = sin(2 * PI * freq * t) * 0.8
            val h2 = sin(2 * PI * freq * 1.5 * t) * exp(-5.0 * t) * 0.35
            val h3 = sin(2 * PI * freq * 2.0 * t) * exp(-8.0 * t) * 0.2
            // Body resonance
            val body = sin(2 * PI * 100.0 * t) * exp(-4.0 * t) * 0.25

            // Membrane thump
            val thump = (Random.nextFloat() * 2f - 1f) * exp(-35.0 * t) * 0.35

            ((fundamental + h2 + h3 + body) * env + thump).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Ke — dry bass tap (muted bayan)
     */
    fun ke(velocity: Float = 0.5f): FloatArray {
        val duration = (SR * 0.1).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR
            val env = exp(-30.0 * t) * velocity

            val tone = sin(2 * PI * 180.0 * t) * 0.4
            val noise = (Random.nextFloat() * 2f - 1f) * exp(-50.0 * t) * 0.5

            ((tone) * env + noise * velocity).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Dha — combined: Ge (bass) + Na (treble) simultaneously
     * The most common and important bol, marks the Sam
     */
    fun dha(velocity: Float = 0.9f): FloatArray {
        val geSound = ge(velocity * 0.7f)
        val naSound = na(velocity * 0.6f)
        val length = maxOf(geSound.size, naSound.size)
        return FloatArray(length) { i ->
            val g = if (i < geSound.size) geSound[i] else 0f
            val n = if (i < naSound.size) naSound[i] else 0f
            (g + n).coerceIn(-1f, 1f)
        }
    }

    /**
     * Dhin — combined: Ghe (open bass) + Tin (treble ring)
     * Richer than Dha, more sustain
     */
    fun dhin(velocity: Float = 0.85f): FloatArray {
        val geSound = ge(velocity * 0.75f)
        val tinSound = tin(velocity * 0.55f)
        val length = maxOf(geSound.size, tinSound.size)
        return FloatArray(length) { i ->
            val g = if (i < geSound.size) geSound[i] else 0f
            val t = if (i < tinSound.size) tinSound[i] else 0f
            (g + t).coerceIn(-1f, 1f)
        }
    }

    /**
     * Generate a bol by name.
     */
    fun playBol(name: String, velocity: Float = 0.8f): FloatArray = when (name.lowercase()) {
        "dha" -> dha(velocity)
        "dhin" -> dhin(velocity)
        "na" -> na(velocity)
        "tin", "ta" -> tin(velocity)
        "ti", "te" -> ti(velocity)
        "ge", "ghe" -> ge(velocity)
        "ke", "ka" -> ke(velocity)
        "-" -> FloatArray(0) // Rest
        else -> ti(velocity)
    }
}
