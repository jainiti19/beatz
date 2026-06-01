package com.beatz.app.data.model

import java.util.UUID

data class Layer(
    val id: String = UUID.randomUUID().toString(),
    val instrument: Instrument,
    val volume: Float = 0.8f,
    val isMuted: Boolean = false,
    val isSolo: Boolean = false
)
