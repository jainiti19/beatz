package com.beatz.app.audio.engine

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Plays multiple audio stems (WAV files) simultaneously with independent volume control.
 * Used for jamming mode: mix bass, drums, other (harmony) stems with adjustable levels.
 */
class StemPlayer {

    companion object {
        const val SAMPLE_RATE = 44100
        private const val BUFFER_SIZE_FRAMES = 2048
    }

    private var audioTrack: AudioTrack? = null
    private var playbackThread: Thread? = null

    // Decoded stem data
    private var stems: Map<String, FloatArray> = emptyMap()
    private var stemVolumes: MutableMap<String, Float> = mutableMapOf()

    @Volatile
    private var isPlaying = false

    @Volatile
    private var playbackPosition = 0

    private val _playbackState = MutableStateFlow(PlaybackState.STOPPED)
    val playbackState: StateFlow<PlaybackState> = _playbackState

    private val _progress = MutableStateFlow(0f)
    val progress: StateFlow<Float> = _progress

    private val _durationSeconds = MutableStateFlow(0f)
    val durationSeconds: StateFlow<Float> = _durationSeconds

    enum class PlaybackState { PLAYING, PAUSED, STOPPED }

    /**
     * Load stem WAV files from a directory.
     * Expects files named: vocals.wav, drums.wav, bass.wav, other.wav
     */
    fun loadStems(stemDir: File): Boolean {
        val stemNames = listOf("vocals", "drums", "bass", "other")
        val loaded = mutableMapOf<String, FloatArray>()

        for (name in stemNames) {
            val file = File(stemDir, "$name.wav")
            if (file.exists()) {
                val samples = decodeWav(file)
                if (samples != null) {
                    loaded[name] = samples
                    // Default: vocals off, everything else on
                    stemVolumes[name] = if (name == "vocals") 0f else 0.8f
                }
            }
        }

        if (loaded.isEmpty()) return false
        stems = loaded

        // Calculate duration from longest stem
        val maxSamples = loaded.values.maxOf { it.size }
        _durationSeconds.value = maxSamples.toFloat() / SAMPLE_RATE

        initAudioTrack()
        return true
    }

    /**
     * Load stems from individual file paths.
     */
    fun loadStemFiles(stemFiles: Map<String, File>): Boolean {
        val loaded = mutableMapOf<String, FloatArray>()

        for ((name, file) in stemFiles) {
            if (file.exists()) {
                val samples = decodeWav(file)
                if (samples != null) {
                    loaded[name] = samples
                    stemVolumes[name] = if (name == "vocals") 0f else 0.8f
                }
            }
        }

        if (loaded.isEmpty()) return false
        stems = loaded

        val maxSamples = loaded.values.maxOf { it.size }
        _durationSeconds.value = maxSamples.toFloat() / SAMPLE_RATE

        initAudioTrack()
        return true
    }

    private fun initAudioTrack() {
        audioTrack?.release()

        val bufferSize = AudioTrack.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_FLOAT
        ).coerceAtLeast(BUFFER_SIZE_FRAMES * 4)

        audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_FLOAT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(bufferSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
    }

    fun setStemVolume(stemName: String, volume: Float) {
        stemVolumes[stemName] = volume.coerceIn(0f, 1f)
    }

    fun getStemVolume(stemName: String): Float = stemVolumes[stemName] ?: 0f

    fun getAvailableStems(): List<String> = stems.keys.toList()

    fun play() {
        if (stems.isEmpty() || isPlaying) return

        isPlaying = true
        _playbackState.value = PlaybackState.PLAYING

        playbackThread = Thread({
            audioTrack?.play()
            mixAndPlay()
        }, "StemPlayerThread").apply {
            priority = Thread.MAX_PRIORITY
            start()
        }
    }

    fun pause() {
        isPlaying = false
        _playbackState.value = PlaybackState.PAUSED
        audioTrack?.pause()
    }

    fun stop() {
        isPlaying = false
        _playbackState.value = PlaybackState.STOPPED
        playbackThread?.join(500)
        playbackThread = null
        audioTrack?.stop()
        audioTrack?.flush()
        playbackPosition = 0
        _progress.value = 0f
    }

    fun seekTo(fraction: Float) {
        val maxSamples = stems.values.maxOfOrNull { it.size } ?: return
        playbackPosition = (fraction * maxSamples).toInt().coerceIn(0, maxSamples)
    }

    fun release() {
        stop()
        audioTrack?.release()
        audioTrack = null
        stems = emptyMap()
    }

    private fun mixAndPlay() {
        val track = audioTrack ?: return
        val maxSamples = stems.values.maxOfOrNull { it.size } ?: return
        val chunkSize = BUFFER_SIZE_FRAMES
        val mixBuffer = FloatArray(chunkSize)

        while (isPlaying && playbackPosition < maxSamples) {
            val remaining = (maxSamples - playbackPosition).coerceAtMost(chunkSize)

            // Mix all stems
            for (i in 0 until remaining) {
                var sample = 0f
                for ((name, data) in stems) {
                    val vol = stemVolumes[name] ?: 0f
                    if (vol > 0f) {
                        val idx = playbackPosition + i
                        if (idx < data.size) {
                            sample += data[idx] * vol
                        }
                    }
                }
                mixBuffer[i] = sample.coerceIn(-1f, 1f)
            }

            track.write(mixBuffer, 0, remaining, AudioTrack.WRITE_BLOCKING)
            playbackPosition += remaining

            _progress.value = playbackPosition.toFloat() / maxSamples
        }

        if (playbackPosition >= maxSamples) {
            _playbackState.value = PlaybackState.STOPPED
            playbackPosition = 0
            _progress.value = 0f
        }
    }

    /**
     * Decode a WAV file to mono float samples.
     * Handles both mono and stereo WAV files.
     */
    private fun decodeWav(file: File): FloatArray? {
        try {
            val bytes = file.readBytes()
            if (bytes.size < 44) return null

            val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)

            // Parse WAV header
            buf.position(22)
            val channels = buf.short.toInt()
            val sampleRate = buf.int
            buf.position(34)
            val bitsPerSample = buf.short.toInt()

            // Find data chunk
            buf.position(36)
            while (buf.remaining() > 8) {
                val chunkId = ByteArray(4)
                buf.get(chunkId)
                val chunkSize = buf.int
                if (String(chunkId) == "data") {
                    val numSamples = chunkSize / (bitsPerSample / 8) / channels

                    // Decode to mono floats
                    val mono = FloatArray(numSamples)
                    for (i in 0 until numSamples) {
                        if (buf.remaining() < channels * (bitsPerSample / 8)) break
                        var sum = 0f
                        for (ch in 0 until channels) {
                            val sample = when (bitsPerSample) {
                                16 -> buf.short.toFloat() / Short.MAX_VALUE
                                24 -> {
                                    val b0 = buf.get().toInt() and 0xFF
                                    val b1 = buf.get().toInt() and 0xFF
                                    val b2 = buf.get().toInt()
                                    ((b2 shl 16) or (b1 shl 8) or b0).toFloat() / 8388607f
                                }
                                32 -> buf.float
                                else -> 0f
                            }
                            sum += sample
                        }
                        mono[i] = sum / channels
                    }

                    // Resample to 44100 if needed
                    return if (sampleRate != SAMPLE_RATE) {
                        resample(mono, sampleRate, SAMPLE_RATE)
                    } else mono
                } else {
                    // Skip non-data chunk
                    if (buf.remaining() >= chunkSize) {
                        buf.position(buf.position() + chunkSize)
                    } else break
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        return null
    }

    private fun resample(input: FloatArray, fromRate: Int, toRate: Int): FloatArray {
        val ratio = toRate.toDouble() / fromRate
        val outputSize = (input.size * ratio).toInt()
        val output = FloatArray(outputSize)
        for (i in output.indices) {
            val srcPos = i / ratio
            val srcIdx = srcPos.toInt()
            val frac = (srcPos - srcIdx).toFloat()
            output[i] = if (srcIdx + 1 < input.size) {
                input[srcIdx] * (1 - frac) + input[srcIdx + 1] * frac
            } else if (srcIdx < input.size) {
                input[srcIdx]
            } else 0f
        }
        return output
    }
}
