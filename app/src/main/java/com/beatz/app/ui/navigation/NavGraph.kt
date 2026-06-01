package com.beatz.app.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.beatz.app.data.model.AnalysisResult
import com.beatz.app.data.model.Song
import com.beatz.app.ui.screens.AnalysisScreen
import com.beatz.app.ui.screens.BeatEditorScreen
import com.beatz.app.ui.screens.HomeScreen

/**
 * Simple state-based navigation.
 * Using manual navigation instead of Compose Navigation to avoid
 * complexity with passing complex objects between destinations.
 */
@Composable
fun BeatzNavGraph(testFilePath: String? = null) {
    // If test file provided, skip directly to analysis
    val initialScreen = if (testFilePath != null) Screen.Analysis else Screen.Home
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

    when (currentScreen) {
        Screen.Home -> {
            HomeScreen(
                onSongReady = { song ->
                    selectedSong = song
                    currentScreen = Screen.Analysis
                }
            )
        }

        Screen.Analysis -> {
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
    Home, Analysis, Editor
}
