package com.beatz.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val BeatzColorScheme = lightColorScheme(
    primary = Color(0xFF00897B),           // Teal
    onPrimary = Color.White,
    primaryContainer = Color(0xFFB2DFDB),  // Light teal
    onPrimaryContainer = Color(0xFF004D40),
    secondary = Color(0xFF43A047),          // Green
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFC8E6C9),
    onSecondaryContainer = Color(0xFF1B5E20),
    tertiary = Color(0xFF26A69A),           // Teal accent
    background = Color.White,
    onBackground = Color(0xFF1C1B1F),
    surface = Color.White,
    onSurface = Color(0xFF1C1B1F),
    surfaceVariant = Color(0xFFE0F2F1),    // Very light teal tint
    onSurfaceVariant = Color(0xFF49454F),
    error = Color(0xFFB3261E),
    onError = Color.White,
    errorContainer = Color(0xFFF9DEDC),
    onErrorContainer = Color(0xFF410E0B),
    outline = Color(0xFF80CBC4),           // Teal outline
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
