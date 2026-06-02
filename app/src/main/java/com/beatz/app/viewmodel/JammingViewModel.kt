package com.beatz.app.viewmodel

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import com.beatz.app.audio.engine.StemPlayer
import com.beatz.app.util.FileUtils
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File

class JammingViewModel(application: Application) : AndroidViewModel(application) {

    var stemPlayer = StemPlayer()
        private set

    private val _stemVolumes = MutableStateFlow<Map<String, Float>>(emptyMap())
    val stemVolumes: StateFlow<Map<String, Float>> = _stemVolumes

    private val _songName = MutableStateFlow("")
    val songName: StateFlow<String> = _songName

    private val _loadState = MutableStateFlow<LoadState>(LoadState.Idle)
    val loadState: StateFlow<LoadState> = _loadState

    val playbackState get() = stemPlayer.playbackState
    val progress get() = stemPlayer.progress
    val durationSeconds get() = stemPlayer.durationSeconds

    /**
     * Load stems from a directory containing vocals.wav, drums.wav, bass.wav, other.wav
     */
    fun loadFromDirectory(stemDir: File, name: String) {
        _loadState.value = LoadState.Loading
        _songName.value = name

        val success = stemPlayer.loadStems(stemDir)
        if (success) {
            updateVolumeState()
            _loadState.value = LoadState.Ready
        } else {
            _loadState.value = LoadState.Error("No stem files found in directory")
        }
    }

    /**
     * Load stems from individual URIs (picked via file picker).
     */
    fun loadFromUris(stemUris: Map<String, Uri>, name: String) {
        _loadState.value = LoadState.Loading
        _songName.value = name

        val context = getApplication<Application>()
        val stemFiles = mutableMapOf<String, File>()

        for ((stemName, uri) in stemUris) {
            try {
                val file = FileUtils.copyToInternal(context, uri, "stem_${stemName}.wav")
                stemFiles[stemName] = file
            } catch (e: Exception) {
                // Skip this stem
            }
        }

        val success = stemPlayer.loadStemFiles(stemFiles)
        if (success) {
            updateVolumeState()
            _loadState.value = LoadState.Ready
        } else {
            _loadState.value = LoadState.Error("Failed to load stems")
        }
    }

    /**
     * Load stems from a directory path string (for testing via intent).
     */
    fun loadFromPath(path: String) {
        // Stop and release previous stems
        stemPlayer.release()
        stemPlayer = StemPlayer()

        val dir = File(path)
        if (dir.isDirectory) {
            loadFromDirectory(dir, dir.name)
        } else {
            _loadState.value = LoadState.Error("Not a directory: $path")
        }
    }

    fun setStemVolume(stemName: String, volume: Float) {
        stemPlayer.setStemVolume(stemName, volume)
        updateVolumeState()
    }

    fun play() = stemPlayer.play()
    fun pause() = stemPlayer.pause()
    fun stop() = stemPlayer.stop()

    fun seekTo(fraction: Float) = stemPlayer.seekTo(fraction)

    private fun updateVolumeState() {
        val volumes = mutableMapOf<String, Float>()
        for (stem in stemPlayer.getAvailableStems()) {
            volumes[stem] = stemPlayer.getStemVolume(stem)
        }
        _stemVolumes.value = volumes
    }

    override fun onCleared() {
        super.onCleared()
        stemPlayer.release()
    }
}

sealed class LoadState {
    data object Idle : LoadState()
    data object Loading : LoadState()
    data object Ready : LoadState()
    data class Error(val message: String) : LoadState()
}
