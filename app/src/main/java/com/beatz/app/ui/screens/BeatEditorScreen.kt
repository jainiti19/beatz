package com.beatz.app.ui.screens

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.beatz.app.data.model.AnalysisResult
import com.beatz.app.ui.components.BpmSlider
import com.beatz.app.ui.components.LayerList
import com.beatz.app.ui.components.TransportBar
import com.beatz.app.viewmodel.BeatEditorViewModel
import com.beatz.app.viewmodel.ExportState

@Composable
fun BeatEditorScreen(
    analysisResult: AnalysisResult,
    songName: String,
    onBack: () -> Unit,
    viewModel: BeatEditorViewModel = viewModel()
) {
    val bpm by viewModel.bpm.collectAsState()
    val key by viewModel.key.collectAsState()
    val layers by viewModel.layers.collectAsState()
    val playbackState by viewModel.playbackState.collectAsState()
    val currentBeat by viewModel.currentBeat.collectAsState()
    val exportState by viewModel.exportState.collectAsState()
    val context = LocalContext.current

    LaunchedEffect(Unit) {
        viewModel.initialize(analysisResult, songName)
    }

    LaunchedEffect(exportState) {
        when (val state = exportState) {
            is ExportState.Done -> {
                Toast.makeText(context, "Exported: ${state.fileName}", Toast.LENGTH_LONG).show()
                viewModel.resetExportState()
            }
            is ExportState.Error -> {
                Toast.makeText(context, "Export failed: ${state.message}", Toast.LENGTH_LONG).show()
                viewModel.resetExportState()
            }
            else -> {}
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Header
        Text(
            text = "Beat Editor",
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )

        // Key display
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant
            )
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "Detected Key",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = key,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface
                )
            }
        }

        // BPM Slider
        BpmSlider(
            bpm = bpm,
            onBpmChange = { viewModel.setBpm(it) }
        )

        // Layer list with volume/mute/solo controls
        LayerList(
            layers = layers,
            onVolumeChange = { id, vol -> viewModel.setLayerVolume(id, vol) },
            onToggleMute = { viewModel.toggleMute(it) },
            onToggleSolo = { viewModel.toggleSolo(it) },
            onChangeInstrument = { id, inst -> viewModel.setLayerInstrument(id, inst) },
            onRemoveLayer = { viewModel.removeLayer(it) },
            onAddLayer = { viewModel.addLayer(it) }
        )

        Spacer(modifier = Modifier.height(4.dp))

        // Transport controls
        TransportBar(
            playbackState = playbackState,
            currentBeat = currentBeat,
            onPlay = { viewModel.play() },
            onPause = { viewModel.pause() },
            onStop = { viewModel.stop() }
        )

        Spacer(modifier = Modifier.height(8.dp))

        // Export button
        when (exportState) {
            is ExportState.Exporting -> {
                Button(
                    onClick = {},
                    enabled = false,
                    modifier = Modifier.fillMaxWidth().height(56.dp)
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.padding(end = 8.dp),
                        color = MaterialTheme.colorScheme.onPrimary
                    )
                    Text("Exporting...")
                }
            }
            else -> {
                Button(
                    onClick = { viewModel.export() },
                    modifier = Modifier.fillMaxWidth().height(56.dp)
                ) {
                    Text("Export as Audio", fontSize = 16.sp)
                }
            }
        }

        // Back button
        OutlinedButton(
            onClick = {
                viewModel.stop()
                onBack()
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Pick Another Song")
        }

        Spacer(modifier = Modifier.height(16.dp))
    }
}
