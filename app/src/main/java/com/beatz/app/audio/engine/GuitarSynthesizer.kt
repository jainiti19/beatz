package com.beatz.app.audio.engine

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

/**
 * Acoustic guitar synthesizer using Karplus-Strong plucked string algorithm.
 * Supports chord voicings and strum patterns for realistic acoustic guitar sound.
 */
object GuitarSynthesizer {

    private const val SAMPLE_RATE = 44100
    private const val NUM_STRINGS = 6

    // Standard guitar open string MIDI notes: E2 A2 D3 G3 B3 E4
    private val OPEN_STRINGS = intArrayOf(40, 45, 50, 55, 59, 64)

    /**
     * Guitar chord voicings as MIDI note arrays (6 strings, -1 = muted).
     * Common open and barre chord voicings.
     */
    private val CHORD_VOICINGS: Map<String, IntArray> = buildMap {
        // Major chords
        put("C",    intArrayOf(-1, 48, 52, 55, 60, 64))
        put("D",    intArrayOf(-1, -1, 50, 57, 62, 66))
        put("E",    intArrayOf(40, 47, 52, 56, 59, 64))
        put("F",    intArrayOf(41, 48, 53, 57, 60, 65))
        put("G",    intArrayOf(43, 47, 50, 55, 59, 67))
        put("A",    intArrayOf(-1, 45, 52, 57, 61, 64))
        put("B",    intArrayOf(-1, 47, 54, 59, 63, 66))

        // Sharp/flat major chords (barre voicings)
        put("C#",   intArrayOf(-1, 49, 53, 56, 61, 65))
        put("D#",   intArrayOf(-1, -1, 51, 58, 63, 67))
        put("F#",   intArrayOf(42, 49, 54, 58, 61, 66))
        put("G#",   intArrayOf(44, 48, 51, 56, 60, 68))
        put("A#",   intArrayOf(-1, 46, 53, 58, 62, 65))

        // Minor chords
        put("Cm",   intArrayOf(-1, 48, 51, 55, 60, 63))
        put("Dm",   intArrayOf(-1, -1, 50, 57, 62, 65))
        put("Em",   intArrayOf(40, 47, 52, 55, 59, 64))
        put("Fm",   intArrayOf(41, 48, 53, 56, 60, 65))
        put("Gm",   intArrayOf(43, 46, 50, 55, 58, 67))
        put("Am",   intArrayOf(-1, 45, 52, 57, 60, 64))
        put("Bm",   intArrayOf(-1, 47, 54, 59, 62, 66))

        // Sharp/flat minor chords
        put("C#m",  intArrayOf(-1, 49, 52, 56, 61, 64))
        put("D#m",  intArrayOf(-1, -1, 51, 58, 63, 66))
        put("F#m",  intArrayOf(42, 49, 54, 57, 61, 66))
        put("G#m",  intArrayOf(44, 47, 51, 56, 59, 68))
        put("A#m",  intArrayOf(-1, 46, 53, 58, 61, 65))

        // Dominant 7th chords
        put("C7",   intArrayOf(-1, 48, 52, 55, 58, 64))
        put("D7",   intArrayOf(-1, -1, 50, 57, 60, 66))
        put("E7",   intArrayOf(40, 47, 50, 56, 59, 64))
        put("F7",   intArrayOf(41, 48, 53, 57, 60, 63))
        put("G7",   intArrayOf(43, 47, 50, 55, 59, 65))
        put("A7",   intArrayOf(-1, 45, 52, 55, 61, 64))
        put("B7",   intArrayOf(-1, 47, 54, 57, 63, 66))

        // Minor 7th chords
        put("Cm7",  intArrayOf(-1, 48, 51, 55, 58, 63))
        put("Dm7",  intArrayOf(-1, -1, 50, 57, 60, 65))
        put("Em7",  intArrayOf(40, 47, 52, 55, 58, 64))
        put("Am7",  intArrayOf(-1, 45, 52, 55, 60, 64))

        // Diminished
        put("Cdim", intArrayOf(-1, 48, 51, 54, -1, -1))
        put("Ddim", intArrayOf(-1, -1, 50, 56, 62, 65))
        put("Edim", intArrayOf(-1, 47, 50, 56, 59, -1))
        put("Bdim", intArrayOf(-1, 47, 53, 56, 59, -1))

        // Sus4
        put("Csus4", intArrayOf(-1, 48, 53, 55, 60, 65))
        put("Dsus4", intArrayOf(-1, -1, 50, 57, 62, 67))
        put("Esus4", intArrayOf(40, 47, 52, 57, 59, 64))
        put("Asus4", intArrayOf(-1, 45, 52, 57, 62, 64))
    }

    /**
     * Strum patterns: sequence of (beatOffset, isDownStrum, velocity).
     * beatOffset is fraction of a beat (0.0 = on beat).
     */
    data class StrumHit(val beatOffset: Float, val isDown: Boolean, val velocity: Float)

    val PATTERN_BALLAD = listOf(
        StrumHit(0.0f, true, 0.9f),     // Beat 1: down
        StrumHit(2.0f, true, 0.7f),     // Beat 3: down
        StrumHit(2.5f, false, 0.5f),    // Beat 3.5: up
        StrumHit(3.5f, false, 0.5f),    // Beat 4.5: up
    )

    val PATTERN_FOLK = listOf(
        StrumHit(0.0f, true, 0.9f),     // Beat 1: down
        StrumHit(0.5f, false, 0.4f),    // up
        StrumHit(1.0f, true, 0.6f),     // Beat 2: down
        StrumHit(1.5f, false, 0.4f),    // up
        StrumHit(2.0f, true, 0.8f),     // Beat 3: down
        StrumHit(2.5f, false, 0.4f),    // up
        StrumHit(3.0f, true, 0.6f),     // Beat 4: down
        StrumHit(3.5f, false, 0.4f),    // up
    )

    val PATTERN_BOLLYWOOD = listOf(
        StrumHit(0.0f, true, 1.0f),     // Beat 1: strong down
        StrumHit(1.0f, true, 0.5f),     // Beat 2: light down
        StrumHit(1.5f, false, 0.4f),    // up
        StrumHit(2.0f, true, 0.8f),     // Beat 3: down
        StrumHit(3.0f, true, 0.5f),     // Beat 4: light down
        StrumHit(3.5f, false, 0.5f),    // up
    )

    /**
     * Synthesize a single guitar string using Karplus-Strong.
     * @param midiNote MIDI note number
     * @param durationSeconds how long the note rings
     * @param velocity 0.0-1.0 pluck strength
     * @return mono PCM samples
     */
    fun synthesizeString(
        midiNote: Int,
        durationSeconds: Float = 1.5f,
        velocity: Float = 0.8f
    ): FloatArray {
        // Slight random detuning per string (real guitars aren't perfectly tuned)
        val detuneCents = (Random.nextFloat() - 0.5f) * 4f // ±2 cents
        val freq = 440.0 * 2.0.pow((midiNote - 69 + detuneCents / 100f) / 12.0)
        val period = (SAMPLE_RATE / freq).toInt().coerceAtLeast(2)
        val numSamples = (SAMPLE_RATE * durationSeconds).toInt()
        val buffer = FloatArray(numSamples)

        // Excitation: shaped noise burst (not pure white noise)
        // Low-pass filter the initial burst for warmer tone
        var prev = 0f
        for (i in 0 until period) {
            val noise = (Random.nextFloat() * 2f - 1f) * velocity
            // Simple low-pass: blend with previous sample for warmth
            val blend = 0.6f + (midiNote - 40) * 0.005f // Higher strings = brighter
            buffer[i] = noise * blend.coerceIn(0.3f, 0.8f) + prev * (1f - blend.coerceIn(0.3f, 0.8f))
            prev = buffer[i]
        }

        // Karplus-Strong with extended averaging (4-point) for richer tone
        val damping = 0.997f - (midiNote - 40) * 0.00025f
        val dampClamped = damping.coerceIn(0.992f, 0.9985f)

        for (i in period until numSamples) {
            // 4-point weighted average for smoother, less metallic sound
            val s0 = buffer[i - period]
            val s1 = if (i - period + 1 < i) buffer[i - period + 1] else s0
            val s2 = if (i - period - 1 >= 0) buffer[i - period - 1] else s0
            buffer[i] = (s0 * 0.5f + s1 * 0.3f + s2 * 0.2f) * dampClamped
        }

        // Body resonance: add subtle low-frequency warmth
        val bodyFreq = 95.0 // ~guitar body resonance
        val bodyAmount = 0.06f * velocity
        for (i in buffer.indices) {
            val t = i.toFloat() / SAMPLE_RATE
            val bodyEnv = exp(-2.0 * t).toFloat()
            buffer[i] += (sin(2.0 * PI * bodyFreq * t).toFloat() * bodyAmount * bodyEnv)
        }

        // Natural decay envelope (not linear)
        for (i in buffer.indices) {
            val t = i.toFloat() / SAMPLE_RATE
            val env = exp(-0.8 * t).toFloat() // Gentle natural decay
            buffer[i] *= env
        }

        // Fade out last 30ms to avoid clicks
        val fadeOut = (SAMPLE_RATE * 0.03f).toInt()
        for (i in maxOf(0, numSamples - fadeOut) until numSamples) {
            buffer[i] *= (numSamples - i).toFloat() / fadeOut
        }

        return buffer
    }

    /**
     * Synthesize a full chord strum (multiple strings with timing offsets).
     * @param chordName e.g. "Am", "G", "D7"
     * @param isDown true = down strum (low to high), false = up strum
     * @param velocity pluck strength 0.0-1.0
     * @param durationSeconds ring time
     * @return mono PCM samples
     */
    fun synthesizeStrum(
        chordName: String,
        isDown: Boolean = true,
        velocity: Float = 0.8f,
        durationSeconds: Float = 1.5f
    ): FloatArray {
        val voicing = getVoicing(chordName)
        val numSamples = (SAMPLE_RATE * durationSeconds).toInt()
        val output = FloatArray(numSamples)

        // Variable strum speed: faster for up strums, with human randomness
        val baseStrumMs = if (isDown) 25f else 18f
        val strumVariation = (Random.nextFloat() - 0.5f) * 10f // ±5ms
        val totalStrumDelay = ((baseStrumMs + strumVariation) / 1000f * SAMPLE_RATE).toInt()

        val stringOrder = if (isDown) (0 until NUM_STRINGS).toList()
                         else (NUM_STRINGS - 1 downTo 0).toList()

        val activeStrings = stringOrder.filter { voicing[it] >= 0 }

        for ((strumIdx, stringIdx) in activeStrings.withIndex()) {
            val midi = voicing[stringIdx]

            // Per-string velocity variation (first/last strings slightly softer)
            val positionFactor = if (strumIdx == 0 || strumIdx == activeStrings.size - 1) 0.75f else 1f
            val humanVelocity = velocity * positionFactor *
                (0.8f + Random.nextFloat() * 0.2f)

            val stringSample = synthesizeString(
                midiNote = midi,
                durationSeconds = durationSeconds,
                velocity = humanVelocity
            )

            // Non-uniform string spacing (accelerating strum)
            val progress = strumIdx.toFloat() / activeStrings.size.coerceAtLeast(1)
            val offset = (totalStrumDelay * progress * progress).toInt() // Accelerating curve
            // Add tiny random jitter per string (±1ms)
            val jitter = (Random.nextFloat() * SAMPLE_RATE * 0.001f).toInt()

            for (i in stringSample.indices) {
                val outIdx = offset + jitter + i
                if (outIdx in output.indices) {
                    output[outIdx] += stringSample[i] / activeStrings.size * 1.8f
                }
            }
        }

        // Gentle saturation instead of hard clip (warmer overdrive)
        for (i in output.indices) {
            val x = output[i]
            output[i] = if (x > 0.7f) 0.7f + (x - 0.7f) * 0.3f
                        else if (x < -0.7f) -0.7f + (x + 0.7f) * 0.3f
                        else x
        }

        return output
    }

    /**
     * Get the MIDI voicing for a chord name, with fallback.
     */
    fun getVoicing(chordName: String): IntArray {
        // Direct match
        CHORD_VOICINGS[chordName]?.let { return it }

        // Try without quality suffix (fall back to major)
        val root = chordName.takeWhile { it.isLetter() || it == '#' || it == 'b' }
        CHORD_VOICINGS[root]?.let { return it }

        // Default: A major
        return CHORD_VOICINGS["A"]!!
    }

    /**
     * Get available strum patterns.
     */
    fun getPatterns(): Map<String, List<StrumHit>> = mapOf(
        "Ballad" to PATTERN_BALLAD,
        "Folk" to PATTERN_FOLK,
        "Bollywood" to PATTERN_BOLLYWOOD,
    )
}
