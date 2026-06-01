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
import com.beatz.app.data.model.Layer
import com.beatz.app.data.model.Scale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class BeatEditorViewModel(application: Application) : AndroidViewModel(application) {

    private val audioEngine = AudioEngine()

    private val _bpm = MutableStateFlow(120f)
    val bpm: StateFlow<Float> = _bpm

    private val _key = MutableStateFlow("C major")
    val key: StateFlow<String> = _key

    private val _scale = MutableStateFlow(Scale.MAJOR)
    val scale: StateFlow<Scale> = _scale

    private var rootMidi: Int = 60

    private val _layers = MutableStateFlow<List<Layer>>(emptyList())
    val layers: StateFlow<List<Layer>> = _layers

    private val _exportState = MutableStateFlow<ExportState>(ExportState.Idle)
    val exportState: StateFlow<ExportState> = _exportState

    val playbackState = audioEngine.playbackState
    val currentBeat = audioEngine.currentBeat

    // Pattern cache per layer
    private val layerPatterns = mutableMapOf<String, BeatPattern>()
    private var songName: String = "unknown"
    private var melodyNotes: List<MelodyNote> = emptyList()

    fun initialize(analysisResult: AnalysisResult, songName: String) {
        this.songName = songName
        this.melodyNotes = analysisResult.melodyNotes
        _bpm.value = analysisResult.bpm
        _key.value = analysisResult.key

        // Parse detected key into root note and scale
        val (root, detectedScale) = Scale.fromKeyString(analysisResult.key)
        rootMidi = root
        _scale.value = detectedScale

        audioEngine.initialize()
        addLayer(Instrument.DRUMS)
    }

    fun addLayer(instrument: Instrument) {
        val layer = Layer(instrument = instrument)
        _layers.value = _layers.value + layer
        regenerateLayerPattern(layer)
        syncEngine()
    }

    fun removeLayer(layerId: String) {
        _layers.value = _layers.value.filter { it.id != layerId }
        layerPatterns.remove(layerId)
        audioEngine.removeLayer(layerId)
        syncEngine()
    }

    fun setLayerVolume(layerId: String, volume: Float) {
        _layers.value = _layers.value.map {
            if (it.id == layerId) it.copy(volume = volume) else it
        }
        syncEngine()
    }

    fun toggleMute(layerId: String) {
        _layers.value = _layers.value.map {
            if (it.id == layerId) it.copy(isMuted = !it.isMuted) else it
        }
        syncEngine()
    }

    fun toggleSolo(layerId: String) {
        _layers.value = _layers.value.map {
            if (it.id == layerId) it.copy(isSolo = !it.isSolo) else it
        }
        syncEngine()
    }

    fun setLayerInstrument(layerId: String, instrument: Instrument) {
        _layers.value = _layers.value.map {
            if (it.id == layerId) it.copy(instrument = instrument) else it
        }
        val layer = _layers.value.find { it.id == layerId } ?: return
        regenerateLayerPattern(layer)
        syncEngine()
    }

    fun setScale(newScale: Scale) {
        _scale.value = newScale
        regenerateAllPatterns()
    }

    fun setBpm(newBpm: Float) {
        _bpm.value = newBpm
        audioEngine.setBpm(newBpm)
        regenerateAllPatterns()
    }

    private fun regenerateAllPatterns() {
        for (layer in _layers.value) {
            regenerateLayerPattern(layer)
        }
        syncEngine()
    }

    fun play() = audioEngine.play()
    fun pause() = audioEngine.pause()
    fun stop() = audioEngine.stop()

    fun export() {
        _exportState.value = ExportState.Exporting

        viewModelScope.launch(Dispatchers.IO) {
            try {
                val barDurationMs = (4 * 60_000.0 / _bpm.value).toLong()
                val totalDurationMs = barDurationMs * 8
                val pcmBuffer = audioEngine.renderToBuffer(totalDurationMs)

                val context = getApplication<Application>()
                val timestamp = System.currentTimeMillis()
                val cleanSongName = songName
                    .substringBeforeLast(".")
                    .replace(Regex("[^a-zA-Z0-9 ]"), "")
                    .trim()
                    .replace(Regex("\\s+"), "_")
                    .take(40)
                    .lowercase()
                val layerNames = _layers.value
                    .filter { !it.isMuted }
                    .joinToString("+") { it.instrument.name.lowercase() }
                val fileName = "beatz_${cleanSongName}_${layerNames}_${_bpm.value.toInt()}bpm_$timestamp"
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

    private fun regenerateLayerPattern(layer: Layer) {
        val pattern = BeatGenerator.generate(
            instrument = layer.instrument,
            bpm = _bpm.value,
            melodyNotes = melodyNotes,
            scale = _scale.value,
            rootMidi = rootMidi
        )
        layerPatterns[layer.id] = pattern
    }

    private fun syncEngine() {
        audioEngine.updateLayers(_layers.value, layerPatterns)
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
