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
import androidx.compose.foundation.clickable
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
    var playbackSpeed by remember { mutableStateOf(1.0f) }
    var mixerExpanded by remember { mutableStateOf(false) }
    var speedExpanded by remember { mutableStateOf(false) }
    var lyricsExpanded by remember { mutableStateOf(false) }

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

    // Load stems
    LaunchedEffect(stemDirPath) {
        loadState = LoadState.Loading
        val success = stemPlayer.loadStems(File(stemDirPath))
        if (!success) {
            loadState = LoadState.Error("No stem files found in directory")
            return@LaunchedEffect
        }
        updateVolumes()
        loadState = LoadState.Ready
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
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    text = "Jamming Mode",
                    fontSize = 28.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    text = songName.replace("_", " "),
                    fontSize = 14.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            OutlinedButton(
                onClick = { stemPlayer.stop(); onBack() }
            ) { Text("Songs", fontSize = 12.sp) }
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
                        modifier = Modifier.size(44.dp)
                    ) { Text("■", fontSize = 16.sp) }

                    Spacer(modifier = Modifier.size(8.dp))

                    FilledIconButton(
                        onClick = {
                            val newFrac = ((progress * duration - 10f) / duration).coerceAtLeast(0f)
                            stemPlayer.seekTo(newFrac)
                        },
                        modifier = Modifier.size(44.dp)
                    ) { Text("-10", fontSize = 12.sp) }

                    Spacer(modifier = Modifier.size(8.dp))

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

                    Spacer(modifier = Modifier.size(8.dp))

                    FilledIconButton(
                        onClick = {
                            val newFrac = ((progress * duration + 10f) / duration).coerceAtMost(1f)
                            stemPlayer.seekTo(newFrac)
                        },
                        modifier = Modifier.size(44.dp)
                    ) { Text("+10", fontSize = 12.sp) }
                }

                // Presets row (always visible — quick access)
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
                            setStemVolume("vocals", 0f); setStemVolume("drums", 0.7f)
                            setStemVolume("bass", 0.8f); setStemVolume("other", 0.4f)
                        },
                        modifier = Modifier.weight(1f)
                    ) { Text("Jamming", fontSize = 12.sp) }
                }

                // --- Collapsible: Stem Mixer ---
                CollapsibleSection(
                    title = "Stem Mixer",
                    expanded = mixerExpanded,
                    onToggle = { mixerExpanded = !mixerExpanded }
                ) {
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
                }

                // --- Collapsible: Speed ---
                CollapsibleSection(
                    title = "Speed" + if (playbackSpeed != 1.0f) " (%.1fx)".format(playbackSpeed) else "",
                    expanded = speedExpanded,
                    onToggle = { speedExpanded = !speedExpanded }
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Slider(
                            value = playbackSpeed,
                            onValueChange = {
                                playbackSpeed = it
                                stemPlayer.setSpeed(it)
                            },
                            valueRange = 0.5f..1.5f,
                            steps = 4,
                            modifier = Modifier.weight(0.7f)
                        )
                        Text(
                            text = "%.1fx".format(playbackSpeed),
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            modifier = Modifier.weight(0.12f)
                        )
                        if (playbackSpeed != 1.0f) {
                            OutlinedButton(
                                onClick = {
                                    playbackSpeed = 1.0f
                                    stemPlayer.setSpeed(1.0f)
                                },
                                modifier = Modifier.weight(0.18f).height(32.dp),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)
                            ) { Text("1x", fontSize = 11.sp) }
                        } else {
                            Spacer(modifier = Modifier.weight(0.18f))
                        }
                    }
                }

                // --- Collapsible: Lyrics ---
                CollapsibleSection(
                    title = "Lyrics",
                    expanded = lyricsExpanded,
                    onToggle = { lyricsExpanded = !lyricsExpanded }
                ) {
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

            }
        }
    }
}

@Composable
private fun CollapsibleSection(
    title: String,
    expanded: Boolean,
    onToggle: () -> Unit,
    content: @Composable () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
        )
    ) {
        Column {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onToggle() }
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                Text(if (expanded) "▲" else "▼", fontSize = 14.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (expanded) {
                Column(
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    content()
                }
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
