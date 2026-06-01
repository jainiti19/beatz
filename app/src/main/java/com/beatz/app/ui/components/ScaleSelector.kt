package com.beatz.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.beatz.app.data.model.Scale

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ScaleSelector(
    selected: Scale,
    onSelect: (Scale) -> Unit
) {
    Column {
        Text(
            text = "Scale",
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Scale.entries.forEach { scale ->
                FilterChip(
                    selected = scale == selected,
                    onClick = { onSelect(scale) },
                    label = { Text(scale.displayName, fontSize = 12.sp) }
                )
            }
        }
    }
}
