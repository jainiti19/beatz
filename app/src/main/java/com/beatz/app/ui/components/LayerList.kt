package com.beatz.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.beatz.app.data.model.Instrument
import com.beatz.app.data.model.Layer

@Composable
fun LayerList(
    layers: List<Layer>,
    onVolumeChange: (String, Float) -> Unit,
    onToggleMute: (String) -> Unit,
    onToggleSolo: (String) -> Unit,
    onChangeInstrument: (String, Instrument) -> Unit,
    onRemoveLayer: (String) -> Unit,
    onAddLayer: (Instrument) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = "Layers",
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        for (layer in layers) {
            LayerCard(
                layer = layer,
                canRemove = layers.size > 1,
                onVolumeChange = { onVolumeChange(layer.id, it) },
                onToggleMute = { onToggleMute(layer.id) },
                onToggleSolo = { onToggleSolo(layer.id) },
                onChangeInstrument = { onChangeInstrument(layer.id, it) },
                onRemove = { onRemoveLayer(layer.id) }
            )
        }

        // Add layer button
        if (layers.size < 5) {
            AddLayerButton(
                existingInstruments = layers.map { it.instrument },
                onAddLayer = onAddLayer
            )
        }
    }
}

@Composable
private fun LayerCard(
    layer: Layer,
    canRemove: Boolean,
    onVolumeChange: (Float) -> Unit,
    onToggleMute: () -> Unit,
    onToggleSolo: () -> Unit,
    onChangeInstrument: (Instrument) -> Unit,
    onRemove: () -> Unit
) {
    var showInstrumentMenu by remember { mutableStateOf(false) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (layer.isMuted)
                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
            else
                MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            // Top row: instrument name + mute/solo/remove
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                // Instrument selector
                TextButton(onClick = { showInstrumentMenu = true }) {
                    Text(
                        text = layer.instrument.displayName,
                        fontWeight = FontWeight.Bold,
                        fontSize = 16.sp
                    )
                }

                DropdownMenu(
                    expanded = showInstrumentMenu,
                    onDismissRequest = { showInstrumentMenu = false }
                ) {
                    Instrument.entries.forEach { inst ->
                        DropdownMenuItem(
                            text = { Text(inst.displayName) },
                            onClick = {
                                onChangeInstrument(inst)
                                showInstrumentMenu = false
                            }
                        )
                    }
                }

                Spacer(modifier = Modifier.weight(1f))

                // Mute chip
                FilterChip(
                    selected = layer.isMuted,
                    onClick = onToggleMute,
                    label = { Text("M", fontSize = 12.sp) },
                    modifier = Modifier.height(28.dp),
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.8f),
                        selectedLabelColor = MaterialTheme.colorScheme.onError
                    )
                )

                Spacer(modifier = Modifier.width(4.dp))

                // Solo chip
                FilterChip(
                    selected = layer.isSolo,
                    onClick = onToggleSolo,
                    label = { Text("S", fontSize = 12.sp) },
                    modifier = Modifier.height(28.dp),
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.tertiary,
                        selectedLabelColor = MaterialTheme.colorScheme.onTertiary
                    )
                )

                if (canRemove) {
                    Spacer(modifier = Modifier.width(4.dp))
                    TextButton(
                        onClick = onRemove,
                        modifier = Modifier.size(28.dp)
                    ) {
                        Text("✕", fontSize = 14.sp, color = MaterialTheme.colorScheme.error)
                    }
                }
            }

            // Volume slider
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = "Vol",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Slider(
                    value = layer.volume,
                    onValueChange = onVolumeChange,
                    valueRange = 0f..1f,
                    modifier = Modifier.weight(1f).padding(horizontal = 8.dp)
                )
                Text(
                    text = "${(layer.volume * 100).toInt()}%",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun AddLayerButton(
    existingInstruments: List<Instrument>,
    onAddLayer: (Instrument) -> Unit
) {
    var showMenu by remember { mutableStateOf(false) }

    FilledTonalButton(
        onClick = { showMenu = true },
        modifier = Modifier.fillMaxWidth().height(40.dp)
    ) {
        Text("+ Add Layer")
    }

    DropdownMenu(
        expanded = showMenu,
        onDismissRequest = { showMenu = false }
    ) {
        Instrument.entries.forEach { inst ->
            DropdownMenuItem(
                text = { Text(inst.displayName) },
                onClick = {
                    onAddLayer(inst)
                    showMenu = false
                }
            )
        }
    }
}
