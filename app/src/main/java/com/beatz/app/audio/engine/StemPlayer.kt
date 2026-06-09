package com.beatz.app.audio.engine

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Plays multiple audio stems (WAV files) simultaneously with independent volume control.
 * Streams from disk to avoid loading entire files into memory.
 */
class StemPlayer {

    companion object {
        const val SAMPLE_RATE = 44100
        private const val MIX_CHUNK_FRAMES = 4096
    }

    private var audioTrack: AudioTrack? = null
    private var playbackThread: Thread? = null

    // Stem file info (not loaded into memory)
    @Volatile
    private var stemFiles: Map<String, StemInfo> = emptyMap()
    private var stemVolumes: MutableMap<String, Float> = mutableMapOf()

    var onFirstPlay: (() -> Unit)? = null

    @Volatile
    private var isPlaying = false

    @Volatile
    private var playbackFramePos = 0L

    @Volatile
    private var speed = 1.0f

    @Volatile
    private var loopStartFrac = 0f
    @Volatile
    private var loopEndFrac = 1f
    @Volatile
    private var loopEnabled = false

    private val _playbackState = MutableStateFlow(PlaybackState.STOPPED)
    val playbackState: StateFlow<PlaybackState> = _playbackState

    private val _progress = MutableStateFlow(0f)
    val progress: StateFlow<Float> = _progress

    private val _durationSeconds = MutableStateFlow(0f)
    val durationSeconds: StateFlow<Float> = _durationSeconds

    enum class PlaybackState { PLAYING, PAUSED, STOPPED }

    private data class StemInfo(
        val file: File,
        val dataOffset: Long,     // byte offset where PCM data starts
        val totalFrames: Long,    // total mono frames
        val channels: Int,
        val bitsPerSample: Int,
        val sampleRate: Int
    )

    /**
     * Load stem WAV files from a directory. Only parses headers, doesn't read audio data.
     */
    fun loadStems(stemDir: File): Boolean {
        val stemNames = listOf("vocals", "drums", "bass", "other")
        val loaded = mutableMapOf<String, StemInfo>()

        for (name in stemNames) {
            val file = File(stemDir, "$name.wav")
            if (file.exists()) {
                val info = parseWavHeader(file)
                if (info != null) {
                    loaded[name] = info
                    stemVolumes[name] = if (name == "vocals") 0f else 0.8f
                }
            }
        }

        if (loaded.isEmpty()) return false
        stemFiles = loaded

        val maxFrames = loaded.values.maxOf { it.totalFrames }
        _durationSeconds.value = maxFrames.toFloat() / SAMPLE_RATE

        initAudioTrack()
        return true
    }

    fun loadStemFiles(files: Map<String, File>): Boolean {
        val loaded = mutableMapOf<String, StemInfo>()
        for ((name, file) in files) {
            if (file.exists()) {
                val info = parseWavHeader(file)
                if (info != null) {
                    loaded[name] = info
                    stemVolumes[name] = if (name == "vocals") 0f else 0.8f
                }
            }
        }
        if (loaded.isEmpty()) return false
        stemFiles = loaded
        val maxFrames = loaded.values.maxOf { it.totalFrames }
        _durationSeconds.value = maxFrames.toFloat() / SAMPLE_RATE
        initAudioTrack()
        return true
    }

    private fun initAudioTrack() {
        audioTrack?.release()
        val bufferSize = AudioTrack.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_FLOAT
        ).coerceAtLeast(MIX_CHUNK_FRAMES * 4)

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

    /**
     * Add a stem dynamically (e.g. a generated guitar track).
     * Can be called after initial loadStems().
     */
    fun addStem(name: String, file: File, defaultVolume: Float = 0.7f): Boolean {
        if (!file.exists()) return false
        val info = parseWavHeader(file) ?: return false
        stemFiles = stemFiles + (name to info)
        stemVolumes[name] = defaultVolume
        return true
    }

    fun setLoop(startFrac: Float, endFrac: Float) {
        loopStartFrac = startFrac.coerceIn(0f, 1f)
        loopEndFrac = endFrac.coerceIn(loopStartFrac, 1f)
        loopEnabled = true
    }

    fun clearLoop() {
        loopEnabled = false
        loopStartFrac = 0f
        loopEndFrac = 1f
    }

    fun isLooping(): Boolean = loopEnabled

    fun removeStem(name: String) {
        stemFiles = stemFiles - name
        stemVolumes.remove(name)
    }

    fun setSpeed(newSpeed: Float) {
        speed = newSpeed.coerceIn(0.5f, 1.5f)
        audioTrack?.playbackRate = (SAMPLE_RATE * speed).toInt()
    }

    fun setStemVolume(stemName: String, volume: Float) {
        stemVolumes[stemName] = volume.coerceIn(0f, 1f)
    }

    fun getStemVolume(stemName: String): Float = stemVolumes[stemName] ?: 0f
    fun getAvailableStems(): List<String> = stemFiles.keys.toList()

    fun play() {
        if (stemFiles.isEmpty() || isPlaying) return
        // Stop old player on first play
        onFirstPlay?.invoke()
        onFirstPlay = null
        isPlaying = true
        _playbackState.value = PlaybackState.PLAYING
        playbackThread = Thread({
            audioTrack?.play()
            streamAndMix()
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
        playbackFramePos = 0
        _progress.value = 0f
    }

    fun seekTo(fraction: Float) {
        val maxFrames = stemFiles.values.maxOfOrNull { it.totalFrames } ?: return
        playbackFramePos = (fraction * maxFrames).toLong().coerceIn(0, maxFrames)
        _progress.value = fraction.coerceIn(0f, 1f)
    }

    fun release() {
        stop()
        audioTrack?.release()
        audioTrack = null
        stemFiles = emptyMap()
    }

    /**
     * Stream audio from disk, mix stems in real-time, write to AudioTrack.
     */
    private fun streamAndMix() {
        val track = audioTrack ?: return
        val maxFrames = stemFiles.values.maxOfOrNull { it.totalFrames } ?: return

        // Open RandomAccessFile handles for each stem
        val readers = mutableMapOf<String, RandomAccessFile>()
        try {
            for ((name, info) in stemFiles) {
                readers[name] = RandomAccessFile(info.file, "r")
            }

            val mixBuffer = FloatArray(MIX_CHUNK_FRAMES)
            // Per-stem read buffer (max: stereo 16-bit = 4 bytes per frame)
            val readBuf = ByteArray(MIX_CHUNK_FRAMES * 4)

            while (isPlaying && playbackFramePos < maxFrames) {
                val framesToRead = MIX_CHUNK_FRAMES.toLong().coerceAtMost(maxFrames - playbackFramePos).toInt()

                // Clear mix buffer
                for (i in 0 until framesToRead) mixBuffer[i] = 0f

                // Open readers for any new stems added dynamically
                val currentStems = stemFiles
                for ((name, info) in currentStems) {
                    if (name !in readers) {
                        try { readers[name] = RandomAccessFile(info.file, "r") } catch (_: Exception) {}
                    }
                }

                // Read and mix each stem
                for ((name, info) in currentStems) {
                    val vol = stemVolumes[name] ?: 0f
                    if (vol <= 0f) continue

                    val raf = readers[name] ?: continue
                    val bytesPerFrame = info.channels * (info.bitsPerSample / 8)
                    val bytesToRead = framesToRead * bytesPerFrame
                    val filePos = info.dataOffset + playbackFramePos * bytesPerFrame

                    if (filePos + bytesToRead > raf.length()) continue

                    raf.seek(filePos)
                    val read = raf.read(readBuf, 0, bytesToRead)
                    if (read <= 0) continue

                    // Decode and mix into buffer
                    val bb = ByteBuffer.wrap(readBuf, 0, read).order(ByteOrder.LITTLE_ENDIAN)
                    for (i in 0 until framesToRead) {
                        if (bb.remaining() < bytesPerFrame) break
                        var sample = 0f
                        for (ch in 0 until info.channels) {
                            sample += when (info.bitsPerSample) {
                                16 -> bb.short.toFloat() / Short.MAX_VALUE
                                24 -> {
                                    val b0 = bb.get().toInt() and 0xFF
                                    val b1 = bb.get().toInt() and 0xFF
                                    val b2 = bb.get().toInt()
                                    ((b2 shl 16) or (b1 shl 8) or b0).toFloat() / 8388607f
                                }
                                else -> { bb.short.toFloat() / Short.MAX_VALUE }
                            }
                        }
                        mixBuffer[i] += (sample / info.channels) * vol
                    }
                }

                // Clip
                for (i in 0 until framesToRead) {
                    mixBuffer[i] = mixBuffer[i].coerceIn(-1f, 1f)
                }

                track.write(mixBuffer, 0, framesToRead, AudioTrack.WRITE_BLOCKING)
                playbackFramePos += framesToRead
                _progress.value = playbackFramePos.toFloat() / maxFrames

                // Loop: jump back to start when reaching loop end
                if (loopEnabled) {
                    val loopEnd = (loopEndFrac * maxFrames).toLong()
                    if (playbackFramePos >= loopEnd) {
                        playbackFramePos = (loopStartFrac * maxFrames).toLong()
                    }
                }
            }
        } finally {
            for (raf in readers.values) {
                try { raf.close() } catch (_: Exception) {}
            }
        }

        if (playbackFramePos >= maxFrames) {
            _playbackState.value = PlaybackState.STOPPED
            playbackFramePos = 0
            _progress.value = 0f
        }
    }

    /**
     * Parse WAV header only — doesn't read audio data.
     */
    private fun parseWavHeader(file: File): StemInfo? {
        try {
            RandomAccessFile(file, "r").use { raf ->
                if (raf.length() < 44) return null

                val header = ByteArray(44)
                raf.read(header)
                val buf = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN)

                buf.position(22)
                val channels = buf.short.toInt()
                val sampleRate = buf.int
                buf.position(34)
                val bitsPerSample = buf.short.toInt()

                // Find data chunk
                raf.seek(36)
                val chunkHeader = ByteArray(8)
                while (raf.filePointer + 8 < raf.length()) {
                    raf.read(chunkHeader)
                    val chunkBuf = ByteBuffer.wrap(chunkHeader).order(ByteOrder.LITTLE_ENDIAN)
                    val id = String(chunkHeader, 0, 4)
                    val size = chunkBuf.getInt(4)

                    if (id == "data") {
                        val dataOffset = raf.filePointer
                        val bytesPerFrame = channels * (bitsPerSample / 8)
                        val totalFrames = size.toLong() / bytesPerFrame

                        return StemInfo(
                            file = file,
                            dataOffset = dataOffset,
                            totalFrames = totalFrames,
                            channels = channels,
                            bitsPerSample = bitsPerSample,
                            sampleRate = sampleRate
                        )
                    } else {
                        raf.seek(raf.filePointer + size)
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        return null
    }
}
