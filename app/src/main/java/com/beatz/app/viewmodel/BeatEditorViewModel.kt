package com.beatz.app.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.beatz.app.audio.engine.AudioEngine
import com.beatz.app.audio.engine.BeatGenerator
import com.beatz.app.audio.export.BeatExporter
import com.beatz.app.audio.analysis.MelodyNote
import com.beatz.app.data.model.AnalysisResult
import com.beatz.app.data.model.BeatPattern
import com.beatz.app.data.model.Instrument
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class BeatEditorViewModel(application: Application) : AndroidViewModel(application) {

    private val audioEngine = AudioEngine()

    private val _bpm = MutableStateFlow(120f)
    val bpm: StateFlow<Float> = _bpm

    private val _instrument = MutableStateFlow(Instrument.DRUMS)
    val instrument: StateFlow<Instrument> = _instrument

    private val _key = MutableStateFlow("C major")
    val key: StateFlow<String> = _key

    private val _exportState = MutableStateFlow<ExportState>(ExportState.Idle)
    val exportState: StateFlow<ExportState> = _exportState

    val playbackState = audioEngine.playbackState
    val currentBeat = audioEngine.currentBeat

    private var currentPattern: BeatPattern? = null
    private var songName: String = "unknown"
    private var melodyNotes: List<MelodyNote> = emptyList()

    fun initialize(analysisResult: AnalysisResult, songName: String) {
        this.songName = songName
        this.melodyNotes = analysisResult.melodyNotes
        _bpm.value = analysisResult.bpm
        _key.value = analysisResult.key
        audioEngine.initialize()
        regeneratePattern()
    }

    fun setBpm(newBpm: Float) {
        _bpm.value = newBpm
        audioEngine.setBpm(newBpm)
        regeneratePattern()
    }

    fun setInstrument(newInstrument: Instrument) {
        _instrument.value = newInstrument
        regeneratePattern()
    }

    fun play() {
        audioEngine.play()
    }

    fun pause() {
        audioEngine.pause()
    }

    fun stop() {
        audioEngine.stop()
    }

    fun export() {
        _exportState.value = ExportState.Exporting

        viewModelScope.launch(Dispatchers.IO) {
            try {
                // Render 8 bars (about 16 seconds at 120 BPM)
                val barDurationMs = (4 * 60_000.0 / _bpm.value).toLong()
                val totalDurationMs = barDurationMs * 8
                val pcmBuffer = audioEngine.renderToBuffer(totalDurationMs)

                val context = getApplication<Application>()
                val timestamp = System.currentTimeMillis()
                // Clean song name: remove extension and non-alphanumeric chars
                val cleanSongName = songName
                    .substringBeforeLast(".")
                    .replace(Regex("[^a-zA-Z0-9 ]"), "")
                    .trim()
                    .replace(Regex("\\s+"), "_")
                    .take(40)
                    .lowercase()
                val fileName = "beatz_${cleanSongName}_${_instrument.value.name.lowercase()}_${_bpm.value.toInt()}bpm_$timestamp"
                val displayName = BeatExporter.export(context, pcmBuffer, fileName)

                _exportState.value = ExportState.Done(displayName)
            } catch (e: Exception) {
                _exportState.value = ExportState.Error(e.message ?: "Export failed")
            }
        }
    }

    fun resetExportState() {
        _exportState.value = ExportState.Idle
    }

    private fun regeneratePattern() {
        val pattern = BeatGenerator.generate(_instrument.value, _bpm.value, melodyNotes)
        currentPattern = pattern
        audioEngine.setPattern(pattern)
    }

    override fun onCleared() {
        super.onCleared()
        audioEngine.release()
    }
}

sealed class ExportState {
    data object Idle : ExportState()
    data object Exporting : ExportState()
    data class Done(val fileName: String) : ExportState()
    data class Error(val message: String) : ExportState()
}
