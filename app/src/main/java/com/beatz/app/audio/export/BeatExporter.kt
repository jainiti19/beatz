package com.beatz.app.audio.export

import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Exports a rendered beat pattern as a WAV audio file.
 * WAV is universally compatible and avoids AAC encoder issues on emulators.
 */
object BeatExporter {

    private const val SAMPLE_RATE = 44100
    private const val CHANNEL_COUNT = 1
    private const val BITS_PER_SAMPLE = 16

    /**
     * Export the given PCM buffer as a WAV file and save to the device's Music directory.
     * @return the display name of the saved file
     */
    fun export(
        context: Context,
        pcmBuffer: FloatArray,
        fileName: String = "beatz_export"
    ): String {
        val outputFile = File(context.cacheDir, "$fileName.wav")

        // Write PCM to WAV
        writeWav(pcmBuffer, outputFile)

        // Save to MediaStore so it appears in the Music folder
        val displayName = "$fileName.wav"
        saveToMediaStore(context, outputFile, displayName)

        // Clean up temp file
        outputFile.delete()

        return displayName
    }

    private fun writeWav(pcmBuffer: FloatArray, outputFile: File) {
        // Convert float PCM to 16-bit PCM
        val shortSamples = ShortArray(pcmBuffer.size) { i ->
            (pcmBuffer[i] * Short.MAX_VALUE).toInt()
                .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }

        val dataSize = shortSamples.size * 2
        val fileSize = 36 + dataSize

        RandomAccessFile(outputFile, "rw").use { raf ->
            val buffer = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)

            // RIFF header
            buffer.put("RIFF".toByteArray())
            buffer.putInt(fileSize)
            buffer.put("WAVE".toByteArray())

            // fmt chunk
            buffer.put("fmt ".toByteArray())
            buffer.putInt(16) // chunk size
            buffer.putShort(1) // PCM format
            buffer.putShort(CHANNEL_COUNT.toShort())
            buffer.putInt(SAMPLE_RATE)
            buffer.putInt(SAMPLE_RATE * CHANNEL_COUNT * BITS_PER_SAMPLE / 8) // byte rate
            buffer.putShort((CHANNEL_COUNT * BITS_PER_SAMPLE / 8).toShort()) // block align
            buffer.putShort(BITS_PER_SAMPLE.toShort())

            // data chunk
            buffer.put("data".toByteArray())
            buffer.putInt(dataSize)

            buffer.flip()
            raf.write(buffer.array())

            // Write samples
            val sampleBuffer = ByteBuffer.allocate(shortSamples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
            for (s in shortSamples) sampleBuffer.putShort(s)
            raf.write(sampleBuffer.array())
        }
    }

    private fun saveToMediaStore(context: Context, sourceFile: File, displayName: String) {
        val values = ContentValues().apply {
            put(MediaStore.Audio.Media.DISPLAY_NAME, displayName)
            put(MediaStore.Audio.Media.MIME_TYPE, "audio/wav")
            put(MediaStore.Audio.Media.RELATIVE_PATH, Environment.DIRECTORY_MUSIC + "/Beatz")
            put(MediaStore.Audio.Media.IS_PENDING, 1)
        }

        val resolver = context.contentResolver
        val uri = resolver.insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values)
            ?: return

        resolver.openOutputStream(uri)?.use { outputStream ->
            sourceFile.inputStream().use { inputStream ->
                inputStream.copyTo(outputStream)
            }
        }

        values.clear()
        values.put(MediaStore.Audio.Media.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
    }
}
