package com.beatz.app.data.model

import com.beatz.app.audio.analysis.MelodyNote

data class AnalysisResult(
    val bpm: Float,
    val key: String,
    val durationSeconds: Float,
    val sampleRate: Int,
    val channels: Int,
    val melodyNotes: List<MelodyNote> = emptyList()
)
