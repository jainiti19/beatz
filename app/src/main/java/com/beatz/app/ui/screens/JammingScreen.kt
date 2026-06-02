package com.beatz.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.beatz.app.audio.engine.StemPlayer
import com.beatz.app.viewmodel.JammingViewModel
import com.beatz.app.viewmodel.LoadState

@Composable
fun JammingScreen(
    stemDirPath: String,
    onBack: () -> Unit,
    viewModel: JammingViewModel = viewModel()
) {
    val loadState by viewModel.loadState.collectAsState()
    val stemVolumes by viewModel.stemVolumes.collectAsState()
    val playbackState by viewModel.playbackState.collectAsState()
    val progress by viewModel.progress.collectAsState()
    val duration by viewModel.durationSeconds.collectAsState()
    val songName by viewModel.songName.collectAsState()

    // Load stems on first composition
    androidx.compose.runtime.LaunchedEffect(Unit) {
        if (loadState is LoadState.Idle) {
            viewModel.loadFromPath(stemDirPath)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Header
        Text(
            text = "Jamming Mode",
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )

        if (songName.isNotEmpty()) {
            Text(
                text = songName,
                fontSize = 16.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        when (loadState) {
            is LoadState.Idle, is LoadState.Loading -> {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    CircularProgressIndicator()
                    Spacer(modifier = Modifier.height(16.dp))
                    Text("Loading stems...")
                }
            }

            is LoadState.Error -> {
                Text(
                    text = (loadState as LoadState.Error).message,
                    color = MaterialTheme.colorScheme.error
                )
                OutlinedButton(onClick = onBack) {
                    Text("Go Back")
                }
            }

            is LoadState.Ready -> {
                // Playback progress bar
                Column {
                    LinearProgressIndicator(
                        progress = { progress },
                        modifier = Modifier.fillMaxWidth().height(8.dp)
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(formatTime((progress * duration).toInt()), fontSize = 12.sp)
                        Text(formatTime(duration.toInt()), fontSize = 12.sp)
                    }
                }

                // Transport controls
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    // Stop
                    FilledIconButton(
                        onClick = { viewModel.stop() },
                        modifier = Modifier.size(48.dp)
                    ) {
                        Text("■", fontSize = 18.sp)
                    }

                    Spacer(modifier = Modifier.size(16.dp))

                    // Play/Pause
                    FilledIconButton(
                        onClick = {
                            when (playbackState) {
                                StemPlayer.PlaybackState.PLAYING -> viewModel.pause()
                                else -> viewModel.play()
                            }
                        },
                        modifier = Modifier.size(64.dp),
                        colors = IconButtonDefaults.filledIconButtonColors(
                            containerColor = MaterialTheme.colorScheme.primary
                        )
                    ) {
                        Text(
                            if (playbackState == StemPlayer.PlaybackState.PLAYING) "❚❚" else "▶",
                            fontSize = 24.sp
                        )
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))

                // Stem mixer
                Text(
                    text = "Stem Mixer",
                    fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold
                )

                val stemDisplayNames = mapOf(
                    "vocals" to "Vocals",
                    "drums" to "Drums",
                    "bass" to "Bass",
                    "other" to "Harmony / Melody"
                )

                val stemOrder = listOf("vocals", "drums", "bass", "other")
                for (stemName in stemOrder) {
                    val volume = stemVolumes[stemName] ?: continue
                    StemMixerCard(
                        name = stemDisplayNames[stemName] ?: stemName,
                        volume = volume,
                        isVocals = stemName == "vocals",
                        onVolumeChange = { viewModel.setStemVolume(stemName, it) }
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Quick presets
                Text(
                    text = "Presets",
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    OutlinedButton(
                        onClick = {
                            viewModel.setStemVolume("vocals", 0f)
                            viewModel.setStemVolume("drums", 0.8f)
                            viewModel.setStemVolume("bass", 0.8f)
                            viewModel.setStemVolume("other", 0.8f)
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Karaoke", fontSize = 12.sp)
                    }

                    OutlinedButton(
                        onClick = {
                            viewModel.setStemVolume("vocals", 0f)
                            viewModel.setStemVolume("drums", 0f)
                            viewModel.setStemVolume("bass", 0.8f)
                            viewModel.setStemVolume("other", 0.8f)
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Unplugged", fontSize = 12.sp)
                    }

                    OutlinedButton(
                        onClick = {
                            viewModel.setStemVolume("vocals", 0f)
                            viewModel.setStemVolume("drums", 0.3f)
                            viewModel.setStemVolume("bass", 0.8f)
                            viewModel.setStemVolume("other", 0.8f)
                        },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Jamming", fontSize = 12.sp)
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                OutlinedButton(
                    onClick = {
                        viewModel.stop()
                        onBack()
                    },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Back to Home")
                }
            }
        }
    }
}

@Composable
private fun StemMixerCard(
    name: String,
    volume: Float,
    isVocals: Boolean,
    onVolumeChange: (Float) -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (volume == 0f)
                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
            else
                MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = name,
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.weight(0.3f)
            )

            Slider(
                value = volume,
                onValueChange = onVolumeChange,
                valueRange = 0f..1f,
                modifier = Modifier.weight(0.55f)
            )

            Text(
                text = if (volume == 0f) "OFF" else "${(volume * 100).toInt()}%",
                fontSize = 12.sp,
                color = if (volume == 0f) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(0.15f)
            )
        }
    }
}

private fun formatTime(seconds: Int): String {
    val m = seconds / 60
    val s = seconds % 60
    return "%d:%02d".format(m, s)
}
