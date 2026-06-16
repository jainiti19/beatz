package com.beatz.app.ui.navigation

import android.os.Environment
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.beatz.app.audio.engine.StemPlayer
import com.beatz.app.data.PlaylistManager
import com.beatz.app.data.model.AnalysisResult
import com.beatz.app.data.model.Song
import com.beatz.app.ui.screens.AnalysisScreen
import com.beatz.app.ui.screens.BeatEditorScreen
import com.beatz.app.ui.screens.HomeScreen
import com.beatz.app.ui.screens.JammingPickerScreen
import com.beatz.app.ui.screens.JammingScreen
import java.io.File

@Composable
fun BeatzNavGraph(testFilePath: String? = null, jammingStemDir: String? = null) {
    val initialScreen = when {
        jammingStemDir != null -> Screen.Jamming
        testFilePath != null -> Screen.Analysis
        else -> Screen.Home
    }
    val initialSong = if (testFilePath != null) {
        Song(
            uri = android.net.Uri.fromFile(java.io.File(testFilePath)),
            displayName = java.io.File(testFilePath).name,
            internalPath = testFilePath
        )
    } else null

    val context = androidx.compose.ui.platform.LocalContext.current

    var currentScreen by remember { mutableStateOf(initialScreen) }
    var selectedSong by remember { mutableStateOf(initialSong) }
    var analysisResult by remember { mutableStateOf<AnalysisResult?>(null) }
    var stemDir by remember { mutableStateOf(jammingStemDir ?: "") }
    var jammingKey by remember { mutableIntStateOf(0) }
    var selectedPlaylist by remember { mutableStateOf<String?>(null) }

    // Shared StemPlayer — survives screen changes
    val sharedPlayer = remember { mutableStateOf<StemPlayer?>(null) }
    var nowPlayingName by remember { mutableStateOf("") }

    // Song list for continuous playback
    var songList by remember { mutableStateOf<List<String>>(emptyList()) }
    var currentSongIndex by remember { mutableIntStateOf(-1) }
    var autoPlayNext by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        onDispose { sharedPlayer.value?.release() }
    }

    // Helper to load a song by path
    fun loadSong(path: String) {
        stemDir = path
        val newSongName = java.io.File(path).name
        if (newSongName != nowPlayingName) {
            sharedPlayer.value?.stop()
            sharedPlayer.value?.release()
            val player = StemPlayer()
            sharedPlayer.value = player
            nowPlayingName = newSongName
        }
        jammingKey++
        currentScreen = Screen.Jamming
    }

    when (currentScreen) {
        Screen.Home -> {
            sharedPlayer.value?.stop()
            sharedPlayer.value?.release()
            sharedPlayer.value = null
            nowPlayingName = ""

            HomeScreen(
                onSongReady = { song ->
                    selectedSong = song
                    currentScreen = Screen.Analysis
                },
                onJammingMode = {
                    currentScreen = Screen.JammingPicker
                }
            )
        }

        Screen.JammingPicker -> {
            BackHandler {
                sharedPlayer.value?.stop()
                sharedPlayer.value?.release()
                sharedPlayer.value = null
                nowPlayingName = ""
                currentScreen = Screen.Home
            }
            JammingPickerScreen(
                onStemDirSelected = { path ->
                    // Build song list from current view for continuous playback
                    val playlistManager = PlaylistManager(context.filesDir)
                    val allDirs = findStemDirectories(context.filesDir)
                    val filtered = if (selectedPlaylist != null) {
                        val names = playlistManager.getPlaylists()[selectedPlaylist] ?: emptyList()
                        allDirs.filter { it.name in names }
                    } else allDirs
                    songList = filtered.map { it.absolutePath }
                    currentSongIndex = songList.indexOf(path).coerceAtLeast(0)
                    loadSong(path)
                },
                onBack = {
                    sharedPlayer.value?.stop()
                    sharedPlayer.value?.release()
                    sharedPlayer.value = null
                    nowPlayingName = ""
                    currentScreen = Screen.Home
                },
                selectedPlaylist = selectedPlaylist,
                onPlaylistChanged = { selectedPlaylist = it },
                nowPlaying = nowPlayingName,
                stemPlayer = sharedPlayer.value,
                onResumePlayer = {
                    currentScreen = Screen.Jamming
                }
            )
        }

        Screen.Jamming -> {
            BackHandler { currentScreen = Screen.JammingPicker }
            androidx.compose.runtime.key(jammingKey) {
                JammingScreen(
                    stemDirPath = stemDir,
                    stemPlayer = sharedPlayer.value ?: StemPlayer().also { sharedPlayer.value = it },
                    onBack = {
                        currentScreen = Screen.JammingPicker
                    },
                    onNextSong = if (songList.size > 1) {
                        {
                            val nextIndex = (currentSongIndex + 1) % songList.size
                            currentSongIndex = nextIndex
                            val nextPath = songList[nextIndex]
                            sharedPlayer.value?.stop()
                            sharedPlayer.value?.release()
                            val player = StemPlayer()
                            sharedPlayer.value = player
                            nowPlayingName = java.io.File(nextPath).name
                            stemDir = nextPath
                            autoPlayNext = true
                            jammingKey++
                        }
                    } else null,
                    nextSongName = if (songList.size > 1) {
                        val nextIndex = (currentSongIndex + 1) % songList.size
                        java.io.File(songList[nextIndex]).name.replace("_", " ")
                    } else null,
                    autoPlay = autoPlayNext.also { autoPlayNext = false },
                    currentPlaylist = selectedPlaylist
                )
            }
        }

        Screen.Analysis -> {
            BackHandler { currentScreen = Screen.Home }
            val song = selectedSong
            if (song != null) {
                AnalysisScreen(
                    filePath = song.internalPath,
                    songName = song.displayName,
                    onAnalysisDone = { result ->
                        analysisResult = result
                        currentScreen = Screen.Editor
                    },
                    onBack = {
                        currentScreen = Screen.Home
                    }
                )
            }
        }

        Screen.Editor -> {
            BackHandler { currentScreen = Screen.Home }
            val result = analysisResult
            if (result != null) {
                BeatEditorScreen(
                    analysisResult = result,
                    songName = selectedSong?.displayName ?: "unknown",
                    onBack = {
                        currentScreen = Screen.Home
                    }
                )
            }
        }
    }
}

private fun findStemDirectories(filesDir: File): List<File> {
    val dirs = mutableListOf<File>()
    val searchPaths = listOf(
        File(filesDir, "stems"),
        File(Environment.getExternalStorageDirectory(), "Music/karaoke/htdemucs"),
        File(Environment.getExternalStorageDirectory(), "Music/karaoke"),
        File(Environment.getExternalStorageDirectory(), "Download/htdemucs"),
    )
    for (basePath in searchPaths) {
        if (basePath.isDirectory) {
            basePath.listFiles()?.forEach { subDir ->
                if (subDir.isDirectory) {
                    val stemNames = listOf("vocals.wav", "drums.wav", "bass.wav", "other.wav")
                    if (stemNames.any { File(subDir, it).exists() }) {
                        dirs.add(subDir)
                    }
                }
            }
        }
    }
    return dirs.sortedBy { it.name }
}

private enum class Screen {
    Home, JammingPicker, Jamming, Analysis, Editor
}
