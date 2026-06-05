package com.beatz.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val BeatzColorScheme = lightColorScheme(
    primary = Color(0xFF2E7D32),           // Dark green
    onPrimary = Color.White,
    primaryContainer = Color(0xFFC8E6C9),  // Light green
    onPrimaryContainer = Color(0xFF1B5E20),
    secondary = Color(0xFF43A047),          // Medium green
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE8F5E9),
    onSecondaryContainer = Color(0xFF2E7D32),
    tertiary = Color(0xFF66BB6A),           // Lighter green
    background = Color.White,
    onBackground = Color(0xFF1C1B1F),
    surface = Color.White,
    onSurface = Color(0xFF1C1B1F),
    surfaceVariant = Color(0xFFF1F8E9),    // Very light green tint
    onSurfaceVariant = Color(0xFF49454F),
    error = Color(0xFFB3261E),
    onError = Color.White,
    errorContainer = Color(0xFFF9DEDC),
    onErrorContainer = Color(0xFF410E0B),
    outline = Color(0xFFA5D6A7),           // Green outline
)

@Composable
fun BeatzTheme(
    darkTheme: Boolean = false,
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = BeatzColorScheme,
        content = content
    )
}
