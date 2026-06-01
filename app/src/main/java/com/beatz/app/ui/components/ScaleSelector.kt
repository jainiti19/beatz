package com.beatz.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.beatz.app.data.model.Raga
import com.beatz.app.data.model.Scale

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ScaleSelector(
    selectedScale: Scale?,
    selectedRaga: Raga?,
    onSelectScale: (Scale) -> Unit,
    onSelectRaga: (Raga) -> Unit
) {
    // Determine which tab is active
    var tabIndex by remember { mutableIntStateOf(if (selectedRaga != null) 1 else 0) }

    Column {
        Text(
            text = "Scale / Raga",
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        TabRow(selectedTabIndex = tabIndex) {
            Tab(selected = tabIndex == 0, onClick = { tabIndex = 0 }) {
                Text("Western", modifier = Modifier.padding(12.dp), fontSize = 13.sp)
            }
            Tab(selected = tabIndex == 1, onClick = { tabIndex = 1 }) {
                Text("Raga", modifier = Modifier.padding(12.dp), fontSize = 13.sp)
            }
        }

        FlowRow(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            if (tabIndex == 0) {
                Scale.entries.forEach { scale ->
                    FilterChip(
                        selected = selectedRaga == null && scale == selectedScale,
                        onClick = { onSelectScale(scale) },
                        label = { Text(scale.displayName, fontSize = 12.sp) }
                    )
                }
            } else {
                Raga.entries.forEach { raga ->
                    FilterChip(
                        selected = raga == selectedRaga,
                        onClick = { onSelectRaga(raga) },
                        label = {
                            Column {
                                Text(raga.displayName, fontSize = 12.sp)
                                Text(raga.mood, fontSize = 9.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    )
                }
            }
        }
    }
}
