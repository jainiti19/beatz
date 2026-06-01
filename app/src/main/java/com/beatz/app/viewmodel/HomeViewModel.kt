package com.beatz.app.viewmodel

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.beatz.app.data.model.Song
import com.beatz.app.util.FileUtils
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class HomeViewModel(application: Application) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow<HomeUiState>(HomeUiState.Idle)
    val uiState: StateFlow<HomeUiState> = _uiState

    fun onSongPicked(uri: Uri) {
        _uiState.value = HomeUiState.Loading

        viewModelScope.launch(Dispatchers.IO) {
            try {
                val context = getApplication<Application>()
                val displayName = FileUtils.getDisplayName(context, uri) ?: "Unknown"
                val internalFile = FileUtils.copyToInternal(context, uri)

                val song = Song(
                    uri = uri,
                    displayName = displayName,
                    internalPath = internalFile.absolutePath
                )

                _uiState.value = HomeUiState.SongReady(song)
            } catch (e: Exception) {
                _uiState.value = HomeUiState.Error(e.message ?: "Failed to load song")
            }
        }
    }

    fun resetState() {
        _uiState.value = HomeUiState.Idle
    }
}

sealed class HomeUiState {
    data object Idle : HomeUiState()
    data object Loading : HomeUiState()
    data class SongReady(val song: Song) : HomeUiState()
    data class Error(val message: String) : HomeUiState()
}
