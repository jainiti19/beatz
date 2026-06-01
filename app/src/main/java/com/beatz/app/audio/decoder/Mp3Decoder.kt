    package com.beatz.app.audio.decoder

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Decoded audio result: raw PCM samples as floats (-1.0 to 1.0).
 */
data class DecodedAudio(
    val samples: FloatArray,
    val sampleRate: Int,
    val channels: Int,
    val durationSeconds: Float
)

/**
 * Decodes MP3 (or any Android-supported audio format) to raw PCM using
 * the built-in MediaExtractor + MediaCodec APIs.
 */
object Mp3Decoder {

    /**
     * @param maxSeconds if > 0, only decode this many seconds (for faster analysis)
     */
    fun decode(file: File, maxSeconds: Float = 0f): DecodedAudio {
        val extractor = MediaExtractor()
        extractor.setDataSource(file.absolutePath)

        // Find the audio track
        var audioTrackIndex = -1
        var format: MediaFormat? = null
        for (i in 0 until extractor.trackCount) {
            val trackFormat = extractor.getTrackFormat(i)
            val mime = trackFormat.getString(MediaFormat.KEY_MIME) ?: ""
            if (mime.startsWith("audio/")) {
                audioTrackIndex = i
                format = trackFormat
                break
            }
        }
        require(audioTrackIndex >= 0 && format != null) { "No audio track found in file" }

        extractor.selectTrack(audioTrackIndex)

        val mime = format.getString(MediaFormat.KEY_MIME)!!
        val sampleRate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE)
        val channels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
        val duration = if (format.containsKey(MediaFormat.KEY_DURATION)) {
            format.getLong(MediaFormat.KEY_DURATION)
        } else 0L

        val codec = MediaCodec.createDecoderByType(mime)
        codec.configure(format, null, null, 0)
        codec.start()

        val pcmChunks = mutableListOf<ShortArray>()
        val bufferInfo = MediaCodec.BufferInfo()
        var inputDone = false
        var outputDone = false
        val timeoutUs = 10_000L
        val maxDecodeSamples = if (maxSeconds > 0) (maxSeconds * sampleRate * channels).toLong() else Long.MAX_VALUE
        var totalDecodedSamples = 0L

        while (!outputDone) {
            // Feed input
            if (!inputDone) {
                val inputIndex = codec.dequeueInputBuffer(timeoutUs)
                if (inputIndex >= 0) {
                    val inputBuffer = codec.getInputBuffer(inputIndex)!!
                    val sampleSize = extractor.readSampleData(inputBuffer, 0)
                    if (sampleSize < 0 || totalDecodedSamples >= maxDecodeSamples) {
                        codec.queueInputBuffer(
                            inputIndex, 0, 0, 0,
                            MediaCodec.BUFFER_FLAG_END_OF_STREAM
                        )
                        inputDone = true
                    } else {
                        val presentationTimeUs = extractor.sampleTime
                        codec.queueInputBuffer(inputIndex, 0, sampleSize, presentationTimeUs, 0)
                        extractor.advance()
                    }
                }
            }

            // Read output
            val outputIndex = codec.dequeueOutputBuffer(bufferInfo, timeoutUs)
            if (outputIndex >= 0) {
                if (bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                    outputDone = true
                }
                val outputBuffer = codec.getOutputBuffer(outputIndex)
                if (outputBuffer != null && bufferInfo.size > 0) {
                    outputBuffer.order(ByteOrder.LITTLE_ENDIAN)
                    val shortBuffer = outputBuffer.asShortBuffer()
                    val shorts = ShortArray(shortBuffer.remaining())
                    shortBuffer.get(shorts)
                    pcmChunks.add(shorts)
                    totalDecodedSamples += shorts.size
                }
                codec.releaseOutputBuffer(outputIndex, false)
            }
        }

        codec.stop()
        codec.release()
        extractor.release()

        // Merge chunks into one array and convert to float
        val totalSamples = pcmChunks.sumOf { it.size }
        val floatSamples = FloatArray(totalSamples)
        var offset = 0
        for (chunk in pcmChunks) {
            for (s in chunk) {
                floatSamples[offset++] = s.toFloat() / Short.MAX_VALUE
            }
        }

        val durationSeconds = if (duration > 0) {
            duration / 1_000_000f
        } else {
            totalSamples.toFloat() / (sampleRate * channels)
        }

        return DecodedAudio(
            samples = floatSamples,
            sampleRate = sampleRate,
            channels = channels,
            durationSeconds = durationSeconds
        )
    }
}
