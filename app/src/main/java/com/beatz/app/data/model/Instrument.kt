package com.beatz.app.data.model

enum class Instrument(val displayName: String, val sampleDir: String) {
    DRUMS("Drums", "drums"),
    TABLA("Tabla", "tabla"),
    GUITAR("Guitar", "guitar"),
    PIANO("Piano", "piano"),
    FLUTE("Flute", "flute");
}
