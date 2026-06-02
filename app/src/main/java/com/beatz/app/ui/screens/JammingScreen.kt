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
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.foundation.layout.heightIn
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.beatz.app.audio.engine.StemPlayer
import com.beatz.app.viewmodel.LoadState
import java.io.File

@Composable
fun JammingScreen(
    stemDirPath: String,
    onBack: () -> Unit
) {
    val stemPlayer = remember(stemDirPath) { StemPlayer() }
    val songName = remember(stemDirPath) { File(stemDirPath).name }
    val context = LocalContext.current

    var loadState by remember(stemDirPath) { mutableStateOf<LoadState>(LoadState.Idle) }
    var stemVolumes by remember(stemDirPath) { mutableStateOf<Map<String, Float>>(emptyMap()) }
    var showLyrics by remember { mutableStateOf(false) }
    var lyricsText by remember(stemDirPath) { mutableStateOf("") }
    var isEditingLyrics by remember { mutableStateOf(false) }

    // Load saved lyrics
    LaunchedEffect(stemDirPath) {
        val lyricsFile = File(context.filesDir, "lyrics/${songName}.txt")
        if (lyricsFile.exists()) {
            lyricsText = lyricsFile.readText()
        }
    }
    val playbackState by stemPlayer.playbackState.collectAsState()
    val progress by stemPlayer.progress.collectAsState()
    val duration by stemPlayer.durationSeconds.collectAsState()

    fun updateVolumes() {
        val vols = mutableMapOf<String, Float>()
        for (stem in stemPlayer.getAvailableStems()) {
            vols[stem] = stemPlayer.getStemVolume(stem)
        }
        stemVolumes = vols
    }

    fun setStemVolume(name: String, vol: Float) {
        stemPlayer.setStemVolume(name, vol)
        updateVolumes()
    }

    LaunchedEffect(stemDirPath) {
        loadState = LoadState.Loading
        val success = stemPlayer.loadStems(File(stemDirPath))
        if (success) {
            updateVolumes()
            loadState = LoadState.Ready
        } else {
            loadState = LoadState.Error("No stem files found in directory")
        }
    }

    DisposableEffect(stemDirPath) {
        onDispose { stemPlayer.release() }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Text(
            text = "Jamming Mode",
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )

        Text(
            text = songName,
            fontSize = 16.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

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
                OutlinedButton(onClick = onBack) { Text("Go Back") }
            }

            is LoadState.Ready -> {
                // Progress bar
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

                // Transport
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    FilledIconButton(
                        onClick = { stemPlayer.stop() },
                        modifier = Modifier.size(48.dp)
                    ) { Text("■", fontSize = 18.sp) }

                    Spacer(modifier = Modifier.size(16.dp))

                    FilledIconButton(
                        onClick = {
                            if (playbackState == StemPlayer.PlaybackState.PLAYING) stemPlayer.pause()
                            else stemPlayer.play()
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

                // Stem Mixer
                Text("Stem Mixer", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)

                val stemDisplayNames = mapOf(
                    "vocals" to "Vocals",
                    "drums" to "Drums",
                    "bass" to "Bass",
                    "other" to "Harmony / Melody"
                )

                for (stemName in listOf("vocals", "drums", "bass", "other")) {
                    val volume = stemVolumes[stemName] ?: continue
                    StemMixerCard(
                        name = stemDisplayNames[stemName] ?: stemName,
                        volume = volume,
                        isVocals = stemName == "vocals",
                        onVolumeChange = { setStemVolume(stemName, it) }
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Presets
                Text("Presets", fontSize = 14.sp, fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    OutlinedButton(
                        onClick = {
                            setStemVolume("vocals", 0f); setStemVolume("drums", 0.8f)
                            setStemVolume("bass", 0.8f); setStemVolume("other", 0.8f)
                        },
                        modifier = Modifier.weight(1f)
                    ) { Text("Karaoke", fontSize = 12.sp) }

                    OutlinedButton(
                        onClick = {
                            setStemVolume("vocals", 0f); setStemVolume("drums", 0f)
                            setStemVolume("bass", 0.8f); setStemVolume("other", 0.8f)
                        },
                        modifier = Modifier.weight(1f)
                    ) { Text("Unplugged", fontSize = 12.sp) }

                    OutlinedButton(
                        onClick = {
                            setStemVolume("vocals", 0f); setStemVolume("drums", 0.3f)
                            setStemVolume("bass", 0.8f); setStemVolume("other", 0.8f)
                        },
                        modifier = Modifier.weight(1f)
                    ) { Text("Jamming", fontSize = 12.sp) }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Lyrics section
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("Lyrics", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                    Switch(
                        checked = showLyrics,
                        onCheckedChange = { showLyrics = it }
                    )
                }

                if (showLyrics) {
                    if (isEditingLyrics || lyricsText.isEmpty()) {
                        OutlinedTextField(
                            value = lyricsText,
                            onValueChange = { lyricsText = it },
                            modifier = Modifier.fillMaxWidth().heightIn(min = 200.dp),
                            placeholder = { Text("Paste lyrics here...") },
                            label = { Text("Lyrics") }
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            OutlinedButton(
                                onClick = {
                                    // Save lyrics to file
                                    val lyricsDir = File(context.filesDir, "lyrics")
                                    lyricsDir.mkdirs()
                                    File(lyricsDir, "${songName}.txt").writeText(lyricsText)
                                    isEditingLyrics = false
                                },
                                modifier = Modifier.weight(1f)
                            ) { Text("Save") }

                            if (lyricsText.isNotEmpty()) {
                                OutlinedButton(
                                    onClick = { isEditingLyrics = false },
                                    modifier = Modifier.weight(1f)
                                ) { Text("Cancel") }
                            }
                        }
                    } else {
                        // Display mode — scrollable lyrics
                        Card(
                            modifier = Modifier.fillMaxWidth(),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.surfaceVariant
                            )
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    text = lyricsText,
                                    fontSize = 16.sp,
                                    lineHeight = 28.sp
                                )
                            }
                        }
                        OutlinedButton(
                            onClick = { isEditingLyrics = true },
                            modifier = Modifier.fillMaxWidth()
                        ) { Text("Edit Lyrics") }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                OutlinedButton(
                    onClick = {
                        stemPlayer.stop()
                        onBack()
                    },
                    modifier = Modifier.fillMaxWidth()
                ) { Text("Pick Another Song") }
            }
        }
    }
}

@Composable
private fun StemMixerCard(
    name: String, volume: Float, isVocals: Boolean, onVolumeChange: (Float) -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (volume == 0f)
                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
            else MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(name, fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(0.3f))
            Slider(value = volume, onValueChange = onVolumeChange, valueRange = 0f..1f, modifier = Modifier.weight(0.55f))
            Text(
                text = if (volume == 0f) "OFF" else "${(volume * 100).toInt()}%",
                fontSize = 12.sp,
                color = if (volume == 0f) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
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
