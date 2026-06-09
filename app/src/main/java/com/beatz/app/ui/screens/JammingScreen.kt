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
import com.beatz.app.audio.engine.CajonSynthesizer
import com.beatz.app.audio.engine.RhythmTrackGenerator
import com.beatz.app.audio.engine.StemPlayer
import com.beatz.app.audio.engine.TaalSystem
import com.beatz.app.viewmodel.LoadState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

@Composable
fun JammingScreen(
    stemDirPath: String,
    stemPlayer: StemPlayer,
    onBack: () -> Unit
) {
    val songName = remember(stemDirPath) { File(stemDirPath).name }
    val context = LocalContext.current

    var loadState by remember(stemDirPath) { mutableStateOf<LoadState>(LoadState.Idle) }
    var stemVolumes by remember(stemDirPath) { mutableStateOf<Map<String, Float>>(emptyMap()) }
    var showLyrics by remember { mutableStateOf(false) }
    var lyricsText by remember(stemDirPath) { mutableStateOf("") }
    var isEditingLyrics by remember { mutableStateOf(false) }
    var playbackSpeed by remember { mutableStateOf(1.0f) }
    var mixerExpanded by remember { mutableStateOf(false) }
    var rhythmExpanded by remember { mutableStateOf(false) }
    var speedExpanded by remember { mutableStateOf(false) }
    var lyricsExpanded by remember { mutableStateOf(false) }
    var rhythmGenerating by remember { mutableStateOf(false) }
    var detectedBpm by remember(stemDirPath) { mutableStateOf(0f) }
    var adjustedBpm by remember(stemDirPath) { mutableStateOf(0f) }
    var loopExpanded by remember { mutableStateOf(false) }
    var loopActive by remember { mutableStateOf(false) }
    var loopStart by remember { mutableStateOf(0f) }
    var loopEnd by remember { mutableStateOf(1f) }
    var activeTaal by remember(stemDirPath) { mutableStateOf<String?>(null) }
    var activeCajon by remember(stemDirPath) { mutableStateOf(false) }

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

    // Load stems + detect BPM
    LaunchedEffect(stemDirPath) {
        loadState = LoadState.Loading
        val success = stemPlayer.loadStems(File(stemDirPath))
        if (!success) {
            loadState = LoadState.Error("No stem files found in directory")
            return@LaunchedEffect
        }
        updateVolumes()
        loadState = LoadState.Ready

        // Detect BPM in background (use drums stem for best accuracy)
        withContext(Dispatchers.Default) {
            val drumsWav = File(stemDirPath, "drums.wav")
            val otherWav = File(stemDirPath, "other.wav")
            val refWav = if (drumsWav.exists()) drumsWav else otherWav
            if (refWav.exists()) {
                detectedBpm = detectBpmFromWav(refWav)
                adjustedBpm = detectedBpm
            }
        }
    }


    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Spacer(modifier = Modifier.height(20.dp))

        // Song title
        Text(
            text = songName.replace("_", " "),
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.primary,
            maxLines = 2
        )

        Spacer(modifier = Modifier.height(4.dp))

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
                // Player card: progress + transport + presets
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                    )
                ) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        // Progress bar
                        LinearProgressIndicator(
                            progress = { progress },
                            modifier = Modifier.fillMaxWidth().height(6.dp)
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(formatTime((progress * duration).toInt()), fontSize = 11.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(formatTime(duration.toInt()), fontSize = 11.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }

                        // Transport
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            FilledIconButton(
                                onClick = { stemPlayer.stop() },
                                modifier = Modifier.size(40.dp)
                            ) { Text("■", fontSize = 14.sp) }

                            Spacer(modifier = Modifier.size(6.dp))

                            FilledIconButton(
                                onClick = {
                                    val newFrac = ((progress * duration - 10f) / duration).coerceAtLeast(0f)
                                    stemPlayer.seekTo(newFrac)
                                },
                                modifier = Modifier.size(40.dp)
                            ) { Text("-10", fontSize = 11.sp) }

                            Spacer(modifier = Modifier.size(6.dp))

                            FilledIconButton(
                                onClick = {
                                    if (playbackState == StemPlayer.PlaybackState.PLAYING) stemPlayer.pause()
                                    else stemPlayer.play()
                                },
                                modifier = Modifier.size(56.dp),
                                colors = IconButtonDefaults.filledIconButtonColors(
                                    containerColor = MaterialTheme.colorScheme.primary
                                )
                            ) {
                                Text(
                                    if (playbackState == StemPlayer.PlaybackState.PLAYING) "❚❚" else "▶",
                                    fontSize = 22.sp
                                )
                            }

                            Spacer(modifier = Modifier.size(6.dp))

                            FilledIconButton(
                                onClick = {
                                    val newFrac = ((progress * duration + 10f) / duration).coerceAtMost(1f)
                                    stemPlayer.seekTo(newFrac)
                                },
                                modifier = Modifier.size(40.dp)
                            ) { Text("+10", fontSize = 11.sp) }
                        }
                        // Presets
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            OutlinedButton(
                                onClick = {
                                    setStemVolume("vocals", 0f); setStemVolume("drums", 0.8f)
                                    setStemVolume("bass", 0.8f); setStemVolume("other", 0.8f)
                                },
                                modifier = Modifier.weight(1f).height(36.dp),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)
                            ) { Text("Karaoke", fontSize = 12.sp) }

                            OutlinedButton(
                                onClick = {
                                    setStemVolume("vocals", 0f); setStemVolume("drums", 0f)
                                    setStemVolume("bass", 0.8f); setStemVolume("other", 0.8f)
                                },
                                modifier = Modifier.weight(1f).height(36.dp),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)
                            ) { Text("Unplugged", fontSize = 12.sp) }

                            OutlinedButton(
                                onClick = {
                                    setStemVolume("vocals", 0f); setStemVolume("drums", 0.7f)
                                    setStemVolume("bass", 0.8f); setStemVolume("other", 0.4f)
                                },
                                modifier = Modifier.weight(1f).height(36.dp),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)
                            ) { Text("Jamming", fontSize = 12.sp) }
                        }
                    }
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
                        "other" to "Harmony / Melody",
                        "tabla" to "Tabla",
                        "cajon" to "Cajon"
                    )
                    for (stemName in listOf("vocals", "drums", "bass", "other", "tabla", "cajon")) {
                        val volume = stemVolumes[stemName] ?: continue
                        StemMixerCard(
                            name = stemDisplayNames[stemName] ?: stemName,
                            volume = volume,
                            isVocals = stemName == "vocals",
                            onVolumeChange = { setStemVolume(stemName, it) }
                        )
                    }
                }

                // --- Collapsible: Add Rhythm ---
                CollapsibleSection(
                    title = "Taal & Rhythm" + if (rhythmGenerating) " (generating...)" else if (activeTaal != null) " (${activeTaal})" else "",
                    expanded = rhythmExpanded,
                    onToggle = { rhythmExpanded = !rhythmExpanded }
                ) {
                    val scope = kotlinx.coroutines.CoroutineScope(Dispatchers.Main)

                    // BPM slider
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("BPM", fontSize = 13.sp, modifier = Modifier.weight(0.12f))
                        Slider(
                            value = adjustedBpm,
                            onValueChange = { adjustedBpm = it },
                            valueRange = 60f..200f,
                            modifier = Modifier.weight(0.6f),
                            enabled = detectedBpm > 0f
                        )
                        Text(
                            text = "${adjustedBpm.toInt()}",
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            modifier = Modifier.weight(0.1f)
                        )
                        if (adjustedBpm != detectedBpm && detectedBpm > 0f) {
                            OutlinedButton(
                                onClick = { adjustedBpm = detectedBpm },
                                modifier = Modifier.weight(0.18f).height(32.dp),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)
                            ) { Text("Reset", fontSize = 10.sp) }
                        } else {
                            Spacer(modifier = Modifier.weight(0.18f))
                        }
                    }

                    // Tabla taals
                    Text("Tabla", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    Spacer(modifier = Modifier.height(2.dp))

                    for (taal in TaalSystem.ALL_TAALS) {
                        val isActive = activeTaal == taal.name
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(taal.displayName, fontSize = 13.sp, fontWeight = FontWeight.Medium)
                                Text(taal.description, fontSize = 10.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            if (!isActive) {
                                OutlinedButton(
                                    onClick = {
                                        scope.launch {
                                            generateAndAddTaal(
                                                stemDirPath, stemPlayer, taal, adjustedBpm,
                                                { rhythmGenerating = it }, { updateVolumes() }
                                            )
                                            activeTaal = taal.name
                                        }
                                    },
                                    modifier = Modifier.height(32.dp),
                                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp),
                                    enabled = !rhythmGenerating && adjustedBpm > 0f
                                ) { Text("Play", fontSize = 11.sp) }
                            } else {
                                OutlinedButton(
                                    onClick = {
                                        stemPlayer.removeStem("tabla")
                                        updateVolumes()
                                        activeTaal = null
                                    },
                                    modifier = Modifier.height(32.dp),
                                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp)
                                ) { Text("Stop", fontSize = 11.sp) }
                            }
                        }
                        Spacer(modifier = Modifier.height(2.dp))
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    // Cajon
                    Text("Cajon", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    Spacer(modifier = Modifier.height(2.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("Pop/Rock beat", fontSize = 13.sp, modifier = Modifier.weight(1f))
                        if (!activeCajon) {
                            OutlinedButton(
                                onClick = {
                                    scope.launch {
                                        generateAndAddRhythm(
                                            stemDirPath, stemPlayer, "cajon",
                                            RhythmTrackGenerator.Instrument.CAJON, "Pop/Rock",
                                            adjustedBpm,
                                            { rhythmGenerating = it }, { updateVolumes() }
                                        )
                                        activeCajon = true
                                    }
                                },
                                modifier = Modifier.height(32.dp),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp),
                                enabled = !rhythmGenerating && adjustedBpm > 0f
                            ) { Text("Play", fontSize = 11.sp) }
                        } else {
                            OutlinedButton(
                                onClick = {
                                    stemPlayer.removeStem("cajon")
                                    updateVolumes()
                                    activeCajon = false
                                },
                                modifier = Modifier.height(32.dp),
                                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp)
                            ) { Text("Stop", fontSize = 11.sp) }
                        }
                    }
                }

                // --- Collapsible: Loop ---
                CollapsibleSection(
                    title = "Loop" + if (loopActive) " (ON)" else "",
                    expanded = loopExpanded,
                    onToggle = { loopExpanded = !loopExpanded }
                ) {
                    Text("Set A-B points to loop a section", fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("A", fontSize = 13.sp, fontWeight = FontWeight.Bold)
                        Slider(
                            value = loopStart,
                            onValueChange = { loopStart = it.coerceAtMost(loopEnd - 0.02f) },
                            valueRange = 0f..1f,
                            modifier = Modifier.weight(1f)
                        )
                        Text(formatTime((loopStart * duration).toInt()), fontSize = 11.sp)
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text("B", fontSize = 13.sp, fontWeight = FontWeight.Bold)
                        Slider(
                            value = loopEnd,
                            onValueChange = { loopEnd = it.coerceAtLeast(loopStart + 0.02f) },
                            valueRange = 0f..1f,
                            modifier = Modifier.weight(1f)
                        )
                        Text(formatTime((loopEnd * duration).toInt()), fontSize = 11.sp)
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OutlinedButton(
                            onClick = {
                                // Set A to current position
                                loopStart = progress
                            },
                            modifier = Modifier.weight(1f)
                        ) { Text("A = Now", fontSize = 11.sp) }
                        OutlinedButton(
                            onClick = {
                                // Set B to current position
                                loopEnd = progress.coerceAtLeast(loopStart + 0.02f)
                            },
                            modifier = Modifier.weight(1f)
                        ) { Text("B = Now", fontSize = 11.sp) }
                        if (!loopActive) {
                            OutlinedButton(
                                onClick = {
                                    stemPlayer.setLoop(loopStart, loopEnd)
                                    stemPlayer.seekTo(loopStart)
                                    loopActive = true
                                },
                                modifier = Modifier.weight(1f)
                            ) { Text("Loop", fontSize = 11.sp) }
                        } else {
                            OutlinedButton(
                                onClick = {
                                    stemPlayer.clearLoop()
                                    loopActive = false
                                },
                                modifier = Modifier.weight(1f)
                            ) { Text("Stop Loop", fontSize = 11.sp) }
                        }
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

/**
 * Detect BPM from a WAV stem (reads first 20s).
 */
private fun detectBpmFromWav(wavFile: File): Float {
    try {
        RandomAccessFile(wavFile, "r").use { raf ->
            if (raf.length() < 44) return 120f
            val header = ByteArray(44)
            raf.read(header)
            val buf = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN)
            buf.position(22)
            val channels = buf.short.toInt()
            val sampleRate = buf.int
            buf.position(34)
            val bitsPerSample = buf.short.toInt()

            raf.seek(36)
            val chunkHeader = ByteArray(8)
            while (raf.filePointer + 8 < raf.length()) {
                raf.read(chunkHeader)
                val id = String(chunkHeader, 0, 4)
                val size = ByteBuffer.wrap(chunkHeader).order(ByteOrder.LITTLE_ENDIAN).getInt(4)
                if (id == "data") {
                    val bytesPerSample = bitsPerSample / 8
                    val bytesPerFrame = channels * bytesPerSample
                    val maxBytes = (20 * sampleRate * bytesPerFrame).coerceAtMost(size)
                        .coerceAtMost((raf.length() - raf.filePointer).toInt())
                    val pcm = ByteArray(maxBytes)
                    raf.readFully(pcm)
                    val bb = ByteBuffer.wrap(pcm).order(ByteOrder.LITTLE_ENDIAN)
                    val samples = FloatArray(maxBytes / bytesPerSample)
                    for (i in samples.indices) {
                        samples[i] = if (bitsPerSample == 16) bb.short.toFloat() / Short.MAX_VALUE
                        else bb.short.toFloat() / Short.MAX_VALUE
                    }
                    val audio = com.beatz.app.audio.decoder.DecodedAudio(samples, sampleRate, channels, samples.size.toFloat() / (sampleRate * channels))
                    return com.beatz.app.audio.analysis.TempoDetector.detectBpm(audio)
                }
                raf.seek(raf.filePointer + size)
            }
        }
    } catch (_: Exception) { }
    return 120f
}

/**
 * Get WAV duration from header.
 */
private fun getWavDuration(wavFile: File): Float {
    try {
        RandomAccessFile(wavFile, "r").use { raf ->
            if (raf.length() < 44) return 0f
            val header = ByteArray(44)
            raf.read(header)
            val buf = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN)
            buf.position(22)
            val channels = buf.short.toInt()
            val sampleRate = buf.int
            buf.position(34)
            val bitsPerSample = buf.short.toInt()
            raf.seek(36)
            val chunkHeader = ByteArray(8)
            while (raf.filePointer + 8 < raf.length()) {
                raf.read(chunkHeader)
                val id = String(chunkHeader, 0, 4)
                val size = ByteBuffer.wrap(chunkHeader).order(ByteOrder.LITTLE_ENDIAN).getInt(4)
                if (id == "data") return size.toFloat() / (channels * (bitsPerSample / 8)) / sampleRate
                raf.seek(raf.filePointer + size)
            }
        }
    } catch (_: Exception) { }
    return 0f
}

private suspend fun generateAndAddRhythm(
    stemDirPath: String,
    stemPlayer: StemPlayer,
    stemName: String,
    instrument: RhythmTrackGenerator.Instrument,
    patternName: String,
    bpm: Float,
    setGenerating: (Boolean) -> Unit,
    updateVolumes: () -> Unit
) {
    setGenerating(true)
    withContext(Dispatchers.Default) {
        val drumsWav = File(stemDirPath, "drums.wav")
        val otherWav = File(stemDirPath, "other.wav")
        val refWav = if (drumsWav.exists()) drumsWav else otherWav

        val duration = getWavDuration(refWav)

        // Delete old cached file
        val outputFile = File(stemDirPath, "$stemName.wav")
        if (outputFile.exists()) outputFile.delete()

        RhythmTrackGenerator.generate(
            bpm = bpm,
            totalDurationSeconds = duration,
            instrument = instrument,
            patternName = patternName,
            outputFile = outputFile
        )
    }

    val outputFile = File(stemDirPath, "$stemName.wav")
    if (outputFile.exists()) {
        stemPlayer.addStem(stemName, outputFile, 0.9f)
        updateVolumes()
    }
    setGenerating(false)
}

private suspend fun generateAndAddTaal(
    stemDirPath: String,
    stemPlayer: StemPlayer,
    taal: com.beatz.app.audio.engine.Taal,
    bpm: Float,
    setGenerating: (Boolean) -> Unit,
    updateVolumes: () -> Unit
) {
    setGenerating(true)
    withContext(Dispatchers.Default) {
        val drumsWav = File(stemDirPath, "drums.wav")
        val otherWav = File(stemDirPath, "other.wav")
        val refWav = if (drumsWav.exists()) drumsWav else otherWav
        val duration = getWavDuration(refWav)

        val outputFile = File(stemDirPath, "tabla.wav")
        if (outputFile.exists()) outputFile.delete()

        TaalSystem.generateTrack(
            taal = taal,
            bpm = bpm,
            totalDurationSeconds = duration,
            outputFile = outputFile
        )
    }

    val outputFile = File(stemDirPath, "tabla.wav")
    if (outputFile.exists()) {
        stemPlayer.removeStem("tabla")
        stemPlayer.addStem("tabla", outputFile, 0.9f)
        updateVolumes()
    }
    setGenerating(false)
}

private fun formatTime(seconds: Int): String {
    val m = seconds / 60
    val s = seconds % 60
    return "%d:%02d".format(m, s)
}
