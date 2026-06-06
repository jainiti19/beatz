package com.beatz.app.ui.navigation

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.beatz.app.data.model.AnalysisResult
import com.beatz.app.data.model.Song
import com.beatz.app.ui.screens.AnalysisScreen
import com.beatz.app.ui.screens.BeatEditorScreen
import com.beatz.app.ui.screens.HomeScreen
import com.beatz.app.ui.screens.JammingPickerScreen
import com.beatz.app.ui.screens.JammingScreen

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

    var currentScreen by remember { mutableStateOf(initialScreen) }
    var selectedSong by remember { mutableStateOf(initialSong) }
    var analysisResult by remember { mutableStateOf<AnalysisResult?>(null) }
    var stemDir by remember { mutableStateOf(jammingStemDir ?: "") }
    var jammingKey by remember { mutableIntStateOf(0) }
    var selectedPlaylist by remember { mutableStateOf<String?>(null) }

    when (currentScreen) {
        Screen.Home -> {
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
            BackHandler { currentScreen = Screen.Home }
            JammingPickerScreen(
                onStemDirSelected = { path ->
                    stemDir = path
                    jammingKey++
                    currentScreen = Screen.Jamming
                },
                onBack = {
                    currentScreen = Screen.Home
                },
                selectedPlaylist = selectedPlaylist,
                onPlaylistChanged = { selectedPlaylist = it }
            )
        }

        Screen.Jamming -> {
            BackHandler { currentScreen = Screen.JammingPicker }
            androidx.compose.runtime.key(jammingKey) {
                JammingScreen(
                    stemDirPath = stemDir,
                    onBack = {
                        currentScreen = Screen.JammingPicker
                    }
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

private enum class Screen {
    Home, JammingPicker, Jamming, Analysis, Editor
}
