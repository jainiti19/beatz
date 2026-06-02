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
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.io.File

/**
 * Lists available stem directories for jamming mode.
 * Looks for folders containing vocals.wav, drums.wav, bass.wav, other.wav
 * in the Music/karaoke/htdemucs directory.
 */
@Composable
fun JammingPickerScreen(
    onStemDirSelected: (String) -> Unit,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val stemDirs = remember { findStemDirectories(context.filesDir) }
    var youtubeUrl by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "Jamming Mode",
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )

        Text(
            text = "Pick a song to jam with",
            fontSize = 16.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        // YouTube URL input
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
            )
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "Add from YouTube",
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 14.sp
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = youtubeUrl,
                    onValueChange = { youtubeUrl = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("Paste YouTube URL...", fontSize = 13.sp) },
                    singleLine = true
                )
                Spacer(modifier = Modifier.height(8.dp))
                Button(
                    onClick = {
                        if (youtubeUrl.contains("youtube.com") || youtubeUrl.contains("youtu.be")) {
                            // Save URL to a file the PC script can watch
                            val queueDir = File(context.filesDir, "youtube_queue")
                            queueDir.mkdirs()
                            val ts = System.currentTimeMillis()
                            File(queueDir, "request_$ts.txt").writeText(youtubeUrl)
                            Toast.makeText(context,
                                "URL queued! Run on PC:\n./scripts/youtube-to-stems.sh '$youtubeUrl'",
                                Toast.LENGTH_LONG).show()
                            youtubeUrl = ""
                        } else {
                            Toast.makeText(context, "Invalid YouTube URL", Toast.LENGTH_SHORT).show()
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = youtubeUrl.isNotBlank()
                ) {
                    Text("Process Song")
                }
                Text(
                    text = "Requires PC processing. Run the script shown in the toast on your computer.",
                    fontSize = 10.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

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
                        text = "Paste a YouTube URL above, then run the processing script on your PC.",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onErrorContainer
                    )
                }
            }
        } else {
            for (dir in stemDirs) {
                val stemCount = countStems(dir)
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onStemDirSelected(dir.absolutePath) },
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp).fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = dir.name,
                                fontSize = 16.sp,
                                fontWeight = FontWeight.Medium
                            )
                            Text(
                                text = "$stemCount stems available",
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Text(
                            text = "▶",
                            fontSize = 24.sp,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        OutlinedButton(
            onClick = onBack,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Back to Home")
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
