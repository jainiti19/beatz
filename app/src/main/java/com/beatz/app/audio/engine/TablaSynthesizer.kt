package com.beatz.app.audio.engine

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin
import kotlin.random.Random

/**
 * Synthesizes tabla sounds using additive synthesis with
 * non-harmonic overtones characteristic of tabla's syahi (black spot).
 */
object TablaSynthesizer {

    private const val SR = 44100

    /**
     * Na — the signature ringing treble hit
     * Tabla's Na has non-harmonic partials due to the syahi
     */
    fun na(velocity: Float = 0.8f): FloatArray {
        val duration = (SR * 0.5).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR

            // Non-harmonic partials (characteristic of tabla)
            // These ratios come from the loaded membrane vibration modes
            val f0 = 350.0
            val p1 = sin(2 * PI * f0 * t) * exp(-3.0 * t) * 0.5
            val p2 = sin(2 * PI * f0 * 1.51 * t) * exp(-3.5 * t) * 0.45
            val p3 = sin(2 * PI * f0 * 1.99 * t) * exp(-4.0 * t) * 0.35
            val p4 = sin(2 * PI * f0 * 2.44 * t) * exp(-5.0 * t) * 0.25
            val p5 = sin(2 * PI * f0 * 2.91 * t) * exp(-6.0 * t) * 0.18
            val p6 = sin(2 * PI * f0 * 3.43 * t) * exp(-7.0 * t) * 0.1

            // Sharp attack click
            val click = (Random.nextFloat() * 2f - 1f) * exp(-100.0 * t) * 0.5
            // Skin noise
            val skinNoise = (Random.nextFloat() * 2f - 1f) * exp(-30.0 * t) * 0.15

            ((p1 + p2 + p3 + p4 + p5 + p6) * velocity + click + skinNoise).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Tin/Ta — closed treble hit, shorter than Na
     */
    fun tin(velocity: Float = 0.7f): FloatArray {
        val duration = (SR * 0.25).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR

            val f0 = 400.0
            val p1 = sin(2 * PI * f0 * t) * exp(-8.0 * t) * 0.5
            val p2 = sin(2 * PI * f0 * 1.5 * t) * exp(-10.0 * t) * 0.4
            val p3 = sin(2 * PI * f0 * 2.2 * t) * exp(-14.0 * t) * 0.3
            val p4 = sin(2 * PI * f0 * 3.0 * t) * exp(-18.0 * t) * 0.15

            val click = (Random.nextFloat() * 2f - 1f) * exp(-80.0 * t) * 0.5

            ((p1 + p2 + p3 + p4) * velocity + click).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Ti/Te — light fingertip tap
     */
    fun ti(velocity: Float = 0.4f): FloatArray {
        val duration = (SR * 0.12).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR
            val tone = sin(2 * PI * 450.0 * t) * exp(-20.0 * t) * 0.4 +
                       sin(2 * PI * 680.0 * t) * exp(-25.0 * t) * 0.2
            val click = (Random.nextFloat() * 2f - 1f) * exp(-60.0 * t) * 0.4
            ((tone + click) * velocity).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Ge/Ghe — open bass hit on bayan with pitch modulation
     * The bayan's pitch bends down as pressure is released
     */
    fun ge(velocity: Float = 0.85f): FloatArray {
        val duration = (SR * 0.5).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR

            // Pitch drops smoothly (mimics hand pressure release)
            val freq = 180.0 + 80.0 * exp(-6.0 * t)
            val env = exp(-3.0 * t) * velocity

            val fundamental = sin(2 * PI * freq * t) * 0.7
            // Bayan overtones (less harmonic than dayan)
            val h2 = sin(2 * PI * freq * 1.6 * t) * exp(-4.0 * t) * 0.3
            val h3 = sin(2 * PI * freq * 2.3 * t) * exp(-6.0 * t) * 0.15
            // Low body thump
            val body = sin(2 * PI * 90.0 * t) * exp(-5.0 * t) * 0.2

            // Membrane slap
            val slap = (Random.nextFloat() * 2f - 1f) * exp(-40.0 * t) * 0.4

            ((fundamental + h2 + h3 + body) * env + slap).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Ke/Ka — muted bass tap (closed bayan)
     */
    fun ke(velocity: Float = 0.5f): FloatArray {
        val duration = (SR * 0.08).toInt()
        return FloatArray(duration) { i ->
            val t = i.toFloat() / SR
            val tone = sin(2 * PI * 200.0 * t) * exp(-35.0 * t) * 0.3
            val noise = (Random.nextFloat() * 2f - 1f) * exp(-50.0 * t) * 0.6
            ((tone + noise) * velocity).toFloat().coerceIn(-1f, 1f)
        }
    }

    /**
     * Dha = Ge + Na (both hands, the most important bol)
     */
    fun dha(velocity: Float = 0.9f): FloatArray {
        val g = ge(velocity * 0.65f)
        val n = na(velocity * 0.55f)
        val length = maxOf(g.size, n.size)
        return FloatArray(length) { i ->
            val gv = if (i < g.size) g[i] else 0f
            val nv = if (i < n.size) n[i] else 0f
            (gv + nv).coerceIn(-1f, 1f)
        }
    }

    /**
     * Dhin = Ge + Tin (both hands, richer sustain)
     */
    fun dhin(velocity: Float = 0.85f): FloatArray {
        val g = ge(velocity * 0.7f)
        val t = tin(velocity * 0.5f)
        val length = maxOf(g.size, t.size)
        return FloatArray(length) { i ->
            val gv = if (i < g.size) g[i] else 0f
            val tv = if (i < t.size) t[i] else 0f
            (gv + tv).coerceIn(-1f, 1f)
        }
    }

    fun playBol(name: String, velocity: Float = 0.8f): FloatArray = when (name.lowercase()) {
        "dha" -> dha(velocity)
        "dhin" -> dhin(velocity)
        "na" -> na(velocity)
        "tin", "ta" -> tin(velocity)
        "ti", "te" -> ti(velocity)
        "ge", "ghe" -> ge(velocity)
        "ke", "ka" -> ke(velocity)
        "-" -> FloatArray(0)
        else -> ti(velocity)
    }
}
