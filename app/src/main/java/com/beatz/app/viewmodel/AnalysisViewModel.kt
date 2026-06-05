package com.beatz.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.beatz.app.audio.analysis.ChordDetector
import com.beatz.app.audio.analysis.KeyDetector
import com.beatz.app.audio.analysis.MelodyExtractor
import com.beatz.app.audio.analysis.TempoDetector
import com.beatz.app.audio.decoder.Mp3Decoder
import com.beatz.app.data.model.AnalysisResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.io.File

class AnalysisViewModel : ViewModel() {

    private val _uiState = MutableStateFlow<AnalysisUiState>(AnalysisUiState.Idle)
    val uiState: StateFlow<AnalysisUiState> = _uiState

    fun analyze(filePath: String) {
        _uiState.value = AnalysisUiState.Analyzing("Decoding audio...")

        viewModelScope.launch(Dispatchers.Default) {
            try {
                // Step 1: Decode first 20 seconds of MP3 to PCM (enough for analysis)
                _uiState.value = AnalysisUiState.Analyzing("Decoding audio...")
                val audio = Mp3Decoder.decode(File(filePath), maxSeconds = 20f)

                // Step 2: Detect tempo
                _uiState.value = AnalysisUiState.Analyzing("Detecting tempo...")
                val bpm = TempoDetector.detectBpm(audio)

                // Step 3: Detect key
                _uiState.value = AnalysisUiState.Analyzing("Detecting key...")
                val key = KeyDetector.detectKey(audio)

                // Step 4: Extract melody
                _uiState.value = AnalysisUiState.Analyzing("Extracting melody...")
                val melodyNotes = MelodyExtractor.extract(audio, bpm)

                // Step 5: Detect chords (decode full song for this)
                _uiState.value = AnalysisUiState.Analyzing("Detecting chords...")
                val fullAudio = Mp3Decoder.decode(File(filePath))
                val chordTimeline = ChordDetector.detect(fullAudio)

                val result = AnalysisResult(
                    bpm = bpm,
                    key = key,
                    durationSeconds = audio.durationSeconds,
                    sampleRate = audio.sampleRate,
                    channels = audio.channels,
                    melodyNotes = melodyNotes,
                    chordTimeline = chordTimeline
                )

                _uiState.value = AnalysisUiState.Done(result)
            } catch (e: Exception) {
                _uiState.value = AnalysisUiState.Error(e.message ?: "Analysis failed")
            }
        }
    }
}

sealed class AnalysisUiState {
    data object Idle : AnalysisUiState()
    data class Analyzing(val step: String) : AnalysisUiState()
    data class Done(val result: AnalysisResult) : AnalysisUiState()
    data class Error(val message: String) : AnalysisUiState()
}
