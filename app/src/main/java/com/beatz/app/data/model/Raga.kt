package com.beatz.app.data.model

/**
 * Indian classical ragas commonly used in Bollywood music.
 * Each raga defines ascending (aroha) and descending (avaroha) note sequences,
 * plus vadi (most important) and samvadi (second most important) notes.
 *
 * Notes are represented as semitone offsets from Sa (root):
 * Sa=0, Re♭=1, Re=2, Ga♭=3, Ga=4, Ma=5, Ma#=6, Pa=7, Dha♭=8, Dha=9, Ni♭=10, Ni=11
 */
enum class Raga(
    val displayName: String,
    val aroha: List<Int>,    // ascending notes (semitone offsets from root)
    val avaroha: List<Int>,  // descending notes
    val vadi: Int,           // most important note
    val samvadi: Int,        // second most important
    val mood: String
) {
    YAMAN(
        "Yaman",
        aroha = listOf(0, 2, 4, 6, 7, 9, 11, 12),    // Sa Re Ga Ma# Pa Dha Ni Sa
        avaroha = listOf(12, 11, 9, 7, 6, 4, 2, 0),
        vadi = 4, samvadi = 9,   // Ga, Dha
        mood = "Happy, evening"
    ),
    BHAIRAVI(
        "Bhairavi",
        aroha = listOf(0, 1, 3, 5, 7, 8, 10, 12),     // Sa Re♭ Ga♭ Ma Pa Dha♭ Ni♭ Sa
        avaroha = listOf(12, 10, 8, 7, 5, 3, 1, 0),
        vadi = 5, samvadi = 0,   // Ma, Sa
        mood = "Emotional, morning"
    ),
    KHAMAJ(
        "Khamaj",
        aroha = listOf(0, 2, 4, 5, 7, 9, 10, 12),     // Sa Re Ga Ma Pa Dha Ni♭ Sa
        avaroha = listOf(12, 11, 10, 9, 7, 5, 4, 2, 0), // Ni used in descent too
        vadi = 4, samvadi = 10,  // Ga, Ni♭
        mood = "Romantic, light"
    ),
    KAFI(
        "Kafi",
        aroha = listOf(0, 2, 3, 5, 7, 9, 10, 12),     // Sa Re Ga♭ Ma Pa Dha Ni♭ Sa
        avaroha = listOf(12, 10, 9, 7, 5, 3, 2, 0),
        vadi = 5, samvadi = 0,   // Ma, Sa
        mood = "Folk, rain songs"
    ),
    BILAWAL(
        "Bilawal",
        aroha = listOf(0, 2, 4, 5, 7, 9, 11, 12),     // Sa Re Ga Ma Pa Dha Ni Sa (like Major)
        avaroha = listOf(12, 11, 9, 7, 5, 4, 2, 0),
        vadi = 9, samvadi = 4,   // Dha, Ga
        mood = "Bright, happy"
    ),
    BHIMPALASI(
        "Bhimpalasi",
        aroha = listOf(0, 3, 5, 7, 9, 10, 12),         // Sa Ga♭ Ma Pa Dha Ni♭ Sa (skip Re)
        avaroha = listOf(12, 10, 9, 7, 5, 3, 2, 0),    // Re appears in descent
        vadi = 5, samvadi = 0,   // Ma, Sa
        mood = "Longing, afternoon"
    ),
    DES(
        "Des",
        aroha = listOf(0, 2, 4, 5, 7, 9, 10, 12),     // Sa Re Ga Ma Pa Dha Ni♭ Sa
        avaroha = listOf(12, 11, 9, 7, 5, 4, 2, 0),    // Ni shuddha in descent
        vadi = 9, samvadi = 4,   // Dha, Ga
        mood = "Patriotic, upbeat"
    ),
    MALKAUNS(
        "Malkauns",
        aroha = listOf(0, 3, 5, 8, 10, 12),            // Sa Ga♭ Ma Dha♭ Ni♭ Sa (pentatonic)
        avaroha = listOf(12, 10, 8, 5, 3, 0),
        vadi = 5, samvadi = 10,  // Ma, Ni♭
        mood = "Serious, late night"
    ),
    BAGESHRI(
        "Bageshri",
        aroha = listOf(0, 3, 5, 7, 9, 10, 12),         // Sa Ga♭ Ma Pa Dha Ni♭ Sa
        avaroha = listOf(12, 10, 9, 7, 5, 3, 2, 0),
        vadi = 5, samvadi = 0,   // Ma, Sa
        mood = "Romantic, night"
    ),
    PILU(
        "Pilu",
        aroha = listOf(0, 2, 3, 5, 7, 8, 10, 12),     // Sa Re Ga♭ Ma Pa Dha♭ Ni♭ Sa
        avaroha = listOf(12, 11, 10, 9, 8, 7, 5, 4, 3, 2, 0), // Very flexible, uses all notes
        vadi = 7, samvadi = 2,   // Pa, Re
        mood = "Film music, flexible"
    );

    /**
     * Get all allowed notes in this raga for a given root, within MIDI range.
     * Combines aroha and avaroha notes (union).
     */
    fun getAllNotes(rootMidi: Int, lowMidi: Int = 48, highMidi: Int = 84): List<Int> {
        val allowedPcs = (aroha + avaroha).map { it % 12 }.toSet()
        val rootPc = rootMidi % 12
        val notes = mutableListOf<Int>()
        for (midi in lowMidi..highMidi) {
            val pc = ((midi % 12) - rootPc + 12) % 12
            if (pc in allowedPcs) notes.add(midi)
        }
        return notes
    }

    /**
     * Snap a MIDI note to this raga, considering melodic direction.
     * @param direction +1 for ascending, -1 for descending, 0 for unknown
     */
    fun snapToRaga(midiNote: Int, rootMidi: Int, direction: Int = 0): Int {
        val rootPc = rootMidi % 12
        val pc = ((midiNote % 12) - rootPc + 12) % 12

        // Choose note set based on direction
        val noteSet = when {
            direction > 0 -> aroha.map { it % 12 }.toSet()
            direction < 0 -> avaroha.map { it % 12 }.toSet()
            else -> (aroha + avaroha).map { it % 12 }.toSet()
        }

        if (pc in noteSet) return midiNote

        // Find nearest allowed note
        var bestDist = 12
        var bestPc = 0
        for (allowed in noteSet) {
            val dist = minOf(
                kotlin.math.abs(pc - allowed),
                12 - kotlin.math.abs(pc - allowed)
            )
            if (dist < bestDist) {
                bestDist = dist
                bestPc = allowed
            }
        }

        val snappedPc = (rootPc + bestPc) % 12
        val octave = midiNote / 12
        var snapped = octave * 12 + snappedPc
        if (snapped > midiNote + 6) snapped -= 12
        if (snapped < midiNote - 6) snapped += 12
        return snapped
    }

    /**
     * Get chord tones for arpeggio: Sa, vadi, samvadi, Pa (or nearest), Sa octave.
     */
    fun getChordTones(rootMidi: Int): List<Int> {
        val tones = mutableListOf<Int>()
        tones.add(rootMidi)                  // Sa
        tones.add(rootMidi + vadi)           // Vadi
        if (7 in (aroha + avaroha).map { it % 12 }.toSet()) {
            tones.add(rootMidi + 7)          // Pa if in raga
        } else {
            tones.add(rootMidi + samvadi)    // Samvadi otherwise
        }
        tones.add(rootMidi + 12)             // Sa octave
        return tones.sorted()
    }
}
