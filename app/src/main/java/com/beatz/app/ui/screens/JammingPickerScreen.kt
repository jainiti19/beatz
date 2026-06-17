package com.beatz.app.ui.screens

import android.content.ClipboardManager
import android.content.Context
import android.os.Environment
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.material3.OutlinedTextField
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import kotlinx.coroutines.delay
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.horizontalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import com.beatz.app.data.PlaylistManager
import java.io.File

/**
 * Lists available stem directories for jamming mode.
 * Looks for folders containing vocals.wav, drums.wav, bass.wav, other.wav
 * in the Music/karaoke/htdemucs directory.
 */
@Composable
fun JammingPickerScreen(
    onStemDirSelected: (String) -> Unit,
    onBack: () -> Unit,
    selectedPlaylist: String? = null,
    onPlaylistChanged: (String?) -> Unit = {},
    nowPlaying: String = "",
    stemPlayer: com.beatz.app.audio.engine.StemPlayer? = null,
    onResumePlayer: () -> Unit = {}
) {
    val context = LocalContext.current
    var stemDirs by remember { mutableStateOf(findStemDirectories(context.filesDir)) }
    var youtubeUrl by remember { mutableStateOf("") }
    var searchQuery by remember { mutableStateOf("") }
    var youtubeExpanded by remember { mutableStateOf(false) }
    var processingStatus by remember { mutableStateOf<List<Pair<String, String>>>(emptyList()) }
    val playlistManager = remember { PlaylistManager(context.filesDir) }
    var playlists by remember { mutableStateOf(playlistManager.getPlaylists()) }
    var showCreatePlaylist by remember { mutableStateOf(false) }
    var deleteSong by remember { mutableStateOf<String?>(null) }
    var deleteConfirmStep by remember { mutableStateOf(0) }
    var newPlaylistName by remember { mutableStateOf("") }
    var editMode by remember { mutableStateOf(false) }
    var addToPlaylistSong by remember { mutableStateOf<String?>(null) }

    // Auto-refresh song list and processing status every 3 seconds
    LaunchedEffect(Unit) {
        while (true) {
            delay(3000)
            stemDirs = findStemDirectories(context.filesDir)
            processingStatus = readProcessingStatus(context.filesDir)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        com.beatz.app.ui.components.TopBar(title = "BeatznBox", onBack = onBack)

        // Mini player bar (shows when a song is playing)
        if (nowPlaying.isNotEmpty() && stemPlayer != null) {
            val playbackState by stemPlayer.playbackState.collectAsState()
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onResumePlayer() },
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer
                )
            ) {
                Row(
                    modifier = Modifier.padding(12.dp).fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            nowPlaying.replace("_", " "),
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            maxLines = 1
                        )
                        Text(
                            if (playbackState == com.beatz.app.audio.engine.StemPlayer.PlaybackState.PLAYING) "Playing" else "Paused",
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.7f)
                        )
                    }
                    androidx.compose.material3.FilledIconButton(
                        onClick = {
                            if (playbackState == com.beatz.app.audio.engine.StemPlayer.PlaybackState.PLAYING)
                                stemPlayer.pause()
                            else stemPlayer.play()
                        },
                        modifier = Modifier.size(36.dp)
                    ) {
                        Text(
                            if (playbackState == com.beatz.app.audio.engine.StemPlayer.PlaybackState.PLAYING) "❚❚" else "▶",
                            fontSize = 14.sp
                        )
                    }
                }
            }
        }

        // --- Let's Prepare (collapsible: YouTube + processing) ---
        val prepareCount = processingStatus.size
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
                        .clickable { youtubeExpanded = !youtubeExpanded }
                        .padding(16.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        "Let's Prepare" + if (prepareCount > 0) " ($prepareCount processing)" else "",
                        fontWeight = FontWeight.Bold, fontSize = 18.sp,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Text(if (youtubeExpanded) "▲" else "▼", fontSize = 14.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (youtubeExpanded) {
                    Column(modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = youtubeUrl,
                            onValueChange = { youtubeUrl = it },
                            modifier = Modifier.fillMaxWidth(),
                            placeholder = { Text("Song name or YouTube URL...", fontSize = 13.sp) },
                            singleLine = true
                        )
                        Button(
                            onClick = {
                                val input = youtubeUrl.trim()
                                if (input.isNotBlank()) {
                                    val queueDir = File(context.filesDir, "youtube_queue")
                                    queueDir.mkdirs()
                                    val ts = System.currentTimeMillis()
                                    val query = if (input.contains("youtube.com") || input.contains("youtu.be"))
                                        input else "search:$input"
                                    File(queueDir, "request_$ts.txt").writeText(query)
                                    Toast.makeText(context, "Queued!", Toast.LENGTH_SHORT).show()
                                    youtubeUrl = ""
                                }
                            },
                            modifier = Modifier.fillMaxWidth(),
                            enabled = youtubeUrl.isNotBlank()
                        ) { Text("Add Song") }

                        // Processing status inside this section
                        for ((name, status) in processingStatus) {
                            val displayStatus = when {
                                status.startsWith("downloading") -> "Downloading..."
                                status.startsWith("separating") -> "Separating stems..."
                                status.startsWith("pushing") -> "Almost ready..."
                                status.startsWith("error") -> "Failed: ${status.substringAfter(":")}"
                                else -> status
                            }
                            val songLabel = status.substringAfter(":", name).replace("_", " ")
                            Card(
                                modifier = Modifier.fillMaxWidth(),
                                colors = CardDefaults.cardColors(
                                    containerColor = MaterialTheme.colorScheme.secondaryContainer
                                )
                            ) {
                                Row(
                                    modifier = Modifier.padding(12.dp).fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(songLabel, fontSize = 13.sp, fontWeight = FontWeight.Medium)
                                        Text(displayStatus, fontSize = 11.sp,
                                            color = MaterialTheme.colorScheme.onSecondaryContainer)
                                    }
                                    if (!status.startsWith("error")) {
                                        androidx.compose.material3.CircularProgressIndicator(
                                            modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // --- Let's Jam (collapsible) ---
        var jamExpanded by remember { mutableStateOf(true) }

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
                        .clickable { jamExpanded = !jamExpanded }
                        .padding(16.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("Let's Jam", fontSize = 18.sp, fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary)
                    Text(if (jamExpanded) "▲" else "▼ (${stemDirs.size} songs)", fontSize = 14.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }

        if (!jamExpanded) return@Column

        // Playlist chips
        if (playlists.isNotEmpty() || stemDirs.isNotEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                FilterChip(
                    selected = selectedPlaylist == null,
                    onClick = { onPlaylistChanged(null) },
                    label = { Text("All", fontSize = 12.sp) }
                )
                for (name in playlists.keys) {
                    FilterChip(
                        selected = selectedPlaylist == name,
                        onClick = { onPlaylistChanged(if (selectedPlaylist == name) null else name) },
                        label = { Text(name, fontSize = 12.sp) }
                    )
                }
                OutlinedButton(
                    onClick = { showCreatePlaylist = true },
                    modifier = Modifier.height(32.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)
                ) { Text("+", fontSize = 14.sp) }
                if (selectedPlaylist != null) {
                    OutlinedButton(
                        onClick = { editMode = !editMode },
                        modifier = Modifier.height(32.dp),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)
                    ) { Text(if (editMode) "Done" else "Edit", fontSize = 12.sp) }
                }
            }
        }

        // Search filter
        if (stemDirs.size > 3) {
            OutlinedTextField(
                value = searchQuery,
                onValueChange = { searchQuery = it },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("Search songs...", fontSize = 13.sp) },
                singleLine = true
            )
        }

        val playlistFiltered = if (selectedPlaylist != null) {
            val songNames = playlists[selectedPlaylist] ?: emptyList()
            val dirMap = stemDirs.associateBy { it.name }
            songNames.mapNotNull { dirMap[it] }
        } else stemDirs

        val filteredDirs = if (searchQuery.isBlank()) playlistFiltered
            else playlistFiltered.filter { it.name.contains(searchQuery, ignoreCase = true) }

        Text(
            text = "${filteredDirs.size} songs",
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        if (stemDirs.isEmpty()) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer
                )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "No songs loaded yet",
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onErrorContainer
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "Paste a YouTube URL above — it will be processed automatically.",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onErrorContainer
                    )
                }
            }
        } else {
            for (dir in filteredDirs) {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { if (!editMode) onStemDirSelected(dir.absolutePath) },
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Row(
                        modifier = Modifier.padding(12.dp).fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        if (editMode) {
                            // Edit mode: reorder + remove + delete
                            Column(
                                modifier = Modifier.padding(end = 8.dp),
                                verticalArrangement = Arrangement.spacedBy(2.dp)
                            ) {
                                Text(
                                    text = "^",
                                    modifier = Modifier
                                        .clickable {
                                            if (selectedPlaylist != null) {
                                                playlistManager.moveSongInPlaylist(selectedPlaylist!!, dir.name, -1)
                                                playlists = playlistManager.getPlaylists()
                                            }
                                        }
                                        .padding(horizontal = 8.dp),
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.primary
                                )
                                Text(
                                    text = "v",
                                    modifier = Modifier
                                        .clickable {
                                            if (selectedPlaylist != null) {
                                                playlistManager.moveSongInPlaylist(selectedPlaylist!!, dir.name, 1)
                                                playlists = playlistManager.getPlaylists()
                                            }
                                        }
                                        .padding(horizontal = 8.dp),
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.primary
                                )
                            }
                        }
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = dir.name.replace("_", " "),
                                fontSize = 15.sp,
                                fontWeight = FontWeight.Medium
                            )
                            val songPlaylists = playlistManager.getPlaylistsForSong(dir.name)
                            if (songPlaylists.isNotEmpty()) {
                                Text(
                                    text = songPlaylists.joinToString(", "),
                                    fontSize = 10.sp,
                                    color = MaterialTheme.colorScheme.primary
                                )
                            }
                        }
                        if (editMode) {
                            // Remove from playlist
                            if (selectedPlaylist != null) {
                                Text(
                                    text = "Remove",
                                    modifier = Modifier
                                        .clickable {
                                            playlistManager.removeSongFromPlaylist(selectedPlaylist!!, dir.name)
                                            playlists = playlistManager.getPlaylists()
                                        }
                                        .padding(horizontal = 6.dp),
                                    fontSize = 12.sp,
                                    color = MaterialTheme.colorScheme.error
                                )
                            }
                            // Delete from device
                            Text(
                                text = "Delete",
                                modifier = Modifier
                                    .clickable { deleteSong = dir.absolutePath }
                                    .padding(horizontal = 6.dp),
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.error.copy(alpha = 0.7f)
                            )
                        } else {
                            // Normal mode: add to playlist
                            Text(
                                text = "+",
                                modifier = Modifier
                                    .clickable { addToPlaylistSong = dir.name }
                                    .padding(horizontal = 8.dp),
                                fontSize = 18.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
        }

    }

    // Create playlist dialog
    if (showCreatePlaylist) {
        AlertDialog(
            onDismissRequest = { showCreatePlaylist = false },
            title = { Text("New Playlist") },
            text = {
                OutlinedTextField(
                    value = newPlaylistName,
                    onValueChange = { newPlaylistName = it },
                    placeholder = { Text("Playlist name") },
                    singleLine = true
                )
            },
            confirmButton = {
                Button(onClick = {
                    if (newPlaylistName.isNotBlank()) {
                        playlistManager.createPlaylist(newPlaylistName.trim())
                        playlists = playlistManager.getPlaylists()
                        newPlaylistName = ""
                        showCreatePlaylist = false
                    }
                }) { Text("Create") }
            },
            dismissButton = {
                OutlinedButton(onClick = { showCreatePlaylist = false }) { Text("Cancel") }
            }
        )
    }

    // Add to playlist dialog
    if (addToPlaylistSong != null) {
        val songName = addToPlaylistSong!!
        val songPlaylists = playlistManager.getPlaylistsForSong(songName)
        AlertDialog(
            onDismissRequest = { addToPlaylistSong = null },
            title = { Text("Add to Playlist") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(songName.replace("_", " "), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(modifier = Modifier.height(8.dp))
                    if (playlists.isEmpty()) {
                        Text("No playlists yet. Create one first.", fontSize = 13.sp)
                    }
                    for (name in playlists.keys) {
                        val isIn = songName in (playlists[name] ?: emptyList())
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    if (isIn) playlistManager.removeSongFromPlaylist(name, songName)
                                    else playlistManager.addSongToPlaylist(name, songName)
                                    playlists = playlistManager.getPlaylists()
                                }
                                .padding(vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = if (isIn) "✓" else "○",
                                fontSize = 16.sp,
                                color = if (isIn) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(end = 12.dp)
                            )
                            Text(name, fontSize = 15.sp)
                        }
                    }
                }
            },
            confirmButton = {
                Button(onClick = { addToPlaylistSong = null }) { Text("Done") }
            }
        )
    }

    // Delete song dialog — double confirmation
    if (deleteSong != null) {
        val songPath = deleteSong!!
        val songDisplayName = File(songPath).name.replace("_", " ")
        if (deleteConfirmStep == 0) deleteConfirmStep = 1

        if (deleteConfirmStep == 1) {
            AlertDialog(
                onDismissRequest = { deleteSong = null; deleteConfirmStep = 0 },
                title = { Text("Delete Song") },
                text = { Text("Remove \"$songDisplayName\" from this device?\n\nThis will delete all stems and lyrics.") },
                confirmButton = {
                    Button(onClick = { deleteConfirmStep = 2 }) { Text("Yes, Delete") }
                },
                dismissButton = {
                    OutlinedButton(onClick = { deleteSong = null; deleteConfirmStep = 0 }) { Text("Cancel") }
                }
            )
        } else if (deleteConfirmStep == 2) {
            AlertDialog(
                onDismissRequest = { deleteSong = null; deleteConfirmStep = 0 },
                title = { Text("Are you sure?") },
                text = { Text("\"$songDisplayName\" will be permanently deleted.") },
                confirmButton = {
                    Button(onClick = {
                        File(songPath).deleteRecursively()
                        val dirName = File(songPath).name
                        for (playlist in playlists.keys) {
                            playlistManager.removeSongFromPlaylist(playlist, dirName)
                        }
                        playlists = playlistManager.getPlaylists()
                        File(context.filesDir, "lyrics/${dirName}.txt").delete()
                        stemDirs = findStemDirectories(context.filesDir)
                        deleteSong = null
                        deleteConfirmStep = 0
                    }) { Text("Delete Permanently") }
                },
                dismissButton = {
                    OutlinedButton(onClick = { deleteSong = null; deleteConfirmStep = 0 }) { Text("Cancel") }
                }
            )
        }
    }
}

private fun findStemDirectories(filesDir: File): List<File> {
    val dirs = mutableListOf<File>()

    // Check app internal storage + external storage
    val searchPaths = listOf(
        File(filesDir, "stems"),
        File(Environment.getExternalStorageDirectory(), "Music/karaoke/htdemucs"),
        File(Environment.getExternalStorageDirectory(), "Music/karaoke"),
        File(Environment.getExternalStorageDirectory(), "Download/htdemucs"),
    )

    for (basePath in searchPaths) {
        if (basePath.isDirectory) {
            basePath.listFiles()?.forEach { subDir ->
                if (subDir.isDirectory && hasStemFiles(subDir)) {
                    dirs.add(subDir)
                }
            }
        }
    }

    return dirs.sortedBy { it.name }
}

private fun hasStemFiles(dir: File): Boolean {
    val stemNames = listOf("vocals.wav", "drums.wav", "bass.wav", "other.wav")
    return stemNames.any { File(dir, it).exists() }
}

private fun countStems(dir: File): Int {
    val stemNames = listOf("vocals.wav", "drums.wav", "bass.wav", "other.wav")
    return stemNames.count { File(dir, it).exists() }
}

private fun readProcessingStatus(filesDir: File): List<Pair<String, String>> {
    val statusDir = File(filesDir, "processing")
    if (!statusDir.isDirectory) return emptyList()
    return statusDir.listFiles()
        ?.filter { it.name.endsWith(".status") }
        ?.map { file ->
            val name = file.name.removeSuffix(".status")
            val status = try { file.readText().trim() } catch (_: Exception) { "processing" }
            name to status
        } ?: emptyList()
}
