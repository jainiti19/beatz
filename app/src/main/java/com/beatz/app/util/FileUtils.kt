package com.beatz.app.util

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File

object FileUtils {

    /**
     * Copy a content URI to the app's internal storage so we can access it
     * reliably without persistent URI permissions.
     * @return the internal file path
     */
    fun copyToInternal(context: Context, uri: Uri, fileName: String? = null): File {
        val displayName = fileName ?: getDisplayName(context, uri) ?: "song.mp3"
        val destFile = File(context.filesDir, "songs/$displayName")
        destFile.parentFile?.mkdirs()

        context.contentResolver.openInputStream(uri)?.use { input ->
            destFile.outputStream().use { output ->
                input.copyTo(output)
            }
        } ?: throw IllegalStateException("Could not open input stream for URI: $uri")

        return destFile
    }

    /**
     * Get the display name of a content URI.
     */
    fun getDisplayName(context: Context, uri: Uri): String? {
        context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (nameIndex >= 0) {
                    return cursor.getString(nameIndex)
                }
            }
        }
        return uri.lastPathSegment
    }
}
