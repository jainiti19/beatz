package com.beatz.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedIconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.beatz.app.audio.engine.AudioEngine

@Composable
fun TransportBar(
    playbackState: AudioEngine.PlaybackState,
    currentBeat: Int,
    onPlay: () -> Unit,
    onPause: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Stop button
        OutlinedIconButton(
            onClick = onStop,
            modifier = Modifier.size(48.dp)
        ) {
            Text("\u25A0", fontSize = 20.sp) // Square (stop symbol)
        }

        Spacer(modifier = Modifier.width(16.dp))

        // Play/Pause button (larger)
        FilledIconButton(
            onClick = {
                when (playbackState) {
                    AudioEngine.PlaybackState.PLAYING -> onPause()
                    else -> onPlay()
                }
            },
            modifier = Modifier.size(64.dp),
            colors = IconButtonDefaults.filledIconButtonColors(
                containerColor = MaterialTheme.colorScheme.primary
            )
        ) {
            Text(
                text = if (playbackState == AudioEngine.PlaybackState.PLAYING) "\u23F8" else "\u25B6",
                fontSize = 24.sp,
                color = MaterialTheme.colorScheme.onPrimary
            )
        }

        Spacer(modifier = Modifier.width(24.dp))

        // Beat indicator
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for (beat in 0..3) {
                Text(
                    text = "\u25CF", // Filled circle
                    fontSize = 16.sp,
                    fontWeight = if (beat == currentBeat && playbackState == AudioEngine.PlaybackState.PLAYING)
                        FontWeight.Bold else FontWeight.Normal,
                    color = if (beat == currentBeat && playbackState == AudioEngine.PlaybackState.PLAYING)
                        MaterialTheme.colorScheme.primary
                    else
                        MaterialTheme.colorScheme.outlineVariant
                )
            }
        }
    }
}
