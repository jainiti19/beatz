package com.beatz.app.data.model

import android.net.Uri

data class Song(
    val uri: Uri,
    val displayName: String,
    val internalPath: String
)
