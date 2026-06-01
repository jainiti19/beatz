package com.beatz.app.data.model

/**
 * A single hit in a beat pattern.
 * @param timeMs when this hit occurs (milliseconds from pattern start)
 * @param sampleName which sample to play (e.g., "kick", "snare", "hihat")
 * @param velocity volume 0.0 to 1.0
 */
data class BeatHit(
    val timeMs: Double,
    val sampleName: String,
    val velocity: Float = 1.0f
)

/**
 * A complete beat pattern: a list of hits that loop.
 * @param hits all the hits in one loop of the pattern
 * @param durationMs how long one loop lasts
 * @param bpm the tempo this pattern was generated for
 */
data class BeatPattern(
    val hits: List<BeatHit>,
    val durationMs: Double,
    val bpm: Float
)
