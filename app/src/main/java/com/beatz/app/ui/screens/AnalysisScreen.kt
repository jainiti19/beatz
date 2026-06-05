package com.beatz.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.beatz.app.audio.analysis.ChordSegment
import com.beatz.app.data.model.AnalysisResult
import com.beatz.app.viewmodel.AnalysisUiState
import com.beatz.app.viewmodel.AnalysisViewModel

@Composable
fun AnalysisScreen(
    filePath: String,
    songName: String,
    onAnalysisDone: (AnalysisResult) -> Unit,
    onBack: () -> Unit,
    viewModel: AnalysisViewModel = viewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    // Start analysis when screen appears
    LaunchedEffect(filePath) {
        if (uiState is AnalysisUiState.Idle) {
            viewModel.analyze(filePath)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        com.beatz.app.ui.components.TopBar(title = "Analyzing", onBack = onBack)

        Text(
            text = songName,
            fontSize = 16.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center
        )

        Spacer(modifier = Modifier.height(32.dp))

        when (val state = uiState) {
            is AnalysisUiState.Idle, is AnalysisUiState.Analyzing -> {
                CircularProgressIndicator(modifier = Modifier.size(64.dp))
                Spacer(modifier = Modifier.height(24.dp))
                Text(
                    text = if (state is AnalysisUiState.Analyzing) state.step else "Starting...",
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

            is AnalysisUiState.Done -> {
                AnalysisResultCard(result = state.result)
                if (state.result.chordTimeline.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(16.dp))
                    ChordTimelineCard(chords = state.result.chordTimeline)
                }
                Spacer(modifier = Modifier.height(32.dp))
                Button(
                    onClick = { onAnalysisDone(state.result) },
                    modifier = Modifier.size(width = 220.dp, height = 56.dp)
                ) {
                    Text("Generate Beat", fontSize = 18.sp)
                }
            }

            is AnalysisUiState.Error -> {
                Text(
                    text = state.message,
                    color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(16.dp))
                Button(onClick = onBack) {
                    Text("Go Back")
                }
            }
        }
    }
}

@Composable
private fun AnalysisResultCard(result: AnalysisResult) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(24.dp)) {
            ResultRow(label = "Tempo", value = "${result.bpm.toInt()} BPM")
            Spacer(modifier = Modifier.height(12.dp))
            ResultRow(label = "Key", value = result.key)
            Spacer(modifier = Modifier.height(12.dp))
            ResultRow(
                label = "Duration",
                value = formatDuration(result.durationSeconds)
            )
        }
    }
}

@Composable
private fun ResultRow(label: String, value: String) {
    Column {
        Text(
            text = label,
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(
            text = value,
            fontSize = 24.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChordTimelineCard(chords: List<ChordSegment>) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(24.dp)) {
            Text(
                text = "Chords",
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.height(8.dp))
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                for (seg in chords) {
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.primaryContainer
                        )
                    ) {
                        Column(
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text(
                                text = seg.chord,
                                fontSize = 16.sp,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.onPrimaryContainer
                            )
                            Text(
                                text = "${formatTime(seg.startTime)}-${formatTime(seg.endTime)}",
                                fontSize = 9.sp,
                                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.7f)
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun formatTime(seconds: Float): String {
    val m = (seconds / 60).toInt()
    val s = (seconds % 60).toInt()
    return "%d:%02d".format(m, s)
}

private fun formatDuration(seconds: Float): String {
    val mins = (seconds / 60).toInt()
    val secs = (seconds % 60).toInt()
    return "${mins}m ${secs}s"
}
