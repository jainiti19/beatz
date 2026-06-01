package com.beatz.app.audio.engine

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import com.beatz.app.data.model.BeatPattern
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Core audio engine using Android's AudioTrack API.
 * Renders beat patterns to PCM in real-time and plays through the speaker.
 */
class AudioEngine {

    companion object {
        const val SAMPLE_RATE = 44100
        private const val BUFFER_SIZE_FRAMES = 1024
    }

    private var audioTrack: AudioTrack? = null
    private var playbackThread: Thread? = null
    private var samples: MutableMap<String, FloatArray> = mutableMapOf()

    @Volatile
    private var currentPattern: BeatPattern? = null

    @Volatile
    private var isPlaying = false

    @Volatile
    private var bpm: Float = 120f

    private val _currentBeat = MutableStateFlow(0)
    val currentBeat: StateFlow<Int> = _currentBeat

    private val _playbackState = MutableStateFlow(PlaybackState.STOPPED)
    val playbackState: StateFlow<PlaybackState> = _playbackState

    enum class PlaybackState { PLAYING, PAUSED, STOPPED }

    /**
     * Initialize the engine and load samples.
     */
    fun initialize() {
        samples = SampleGenerator.generateAllSamples().toMutableMap()

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

    /**
     * Set the beat pattern to play.
     * Pre-generates any pitched samples the pattern needs.
     */
    fun setPattern(pattern: BeatPattern) {
        // Generate any melodic samples that don't exist yet
        for (hit in pattern.hits) {
            if (hit.sampleName !in samples) {
                val generated = generatePitchedSample(hit.sampleName)
                if (generated != null) {
                    samples[hit.sampleName] = generated
                }
            }
        }
        currentPattern = pattern
        bpm = pattern.bpm
    }

    /**
     * Dynamically generate a pitched sample based on its name.
     * Format: "piano_60", "guitar_64", "flute_72_long", "flute_72_short"
     */
    private fun generatePitchedSample(name: String): FloatArray? {
        return when {
            name.startsWith("piano_") -> {
                val midi = name.removePrefix("piano_").toIntOrNull() ?: return null
                SampleGenerator.generatePianoNote(midi)
            }
            name.startsWith("guitar_") -> {
                val midi = name.removePrefix("guitar_").toIntOrNull() ?: return null
                SampleGenerator.generateGuitarNote(midi)
            }
            name.startsWith("flute_") -> {
                // Format: flute_72_long or flute_72_short
                val parts = name.removePrefix("flute_").split("_")
                val midi = parts.getOrNull(0)?.toIntOrNull() ?: return null
                val isLong = parts.getOrNull(1) != "short"
                SampleGenerator.generateFluteNote(midi, isLong)
            }
            else -> null
        }
    }

    fun getSampleCount(): Int = samples.size

    /**
     * Update BPM on the fly — regenerates timing without stopping playback.
     */
    fun setBpm(newBpm: Float) {
        bpm = newBpm
    }

    /**
     * Start playing the current pattern in a loop.
     */
    fun play() {
        if (currentPattern == null || isPlaying) return

        isPlaying = true
        _playbackState.value = PlaybackState.PLAYING

        playbackThread = Thread({
            audioTrack?.play()
            playLoop()
        }, "BeatzAudioThread").apply {
            priority = Thread.MAX_PRIORITY
            start()
        }
    }

    /**
     * Pause playback.
     */
    fun pause() {
        isPlaying = false
        _playbackState.value = PlaybackState.PAUSED
        audioTrack?.pause()
    }

    /**
     * Stop playback and reset position.
     */
    fun stop() {
        isPlaying = false
        _playbackState.value = PlaybackState.STOPPED
        playbackThread?.join(500)
        playbackThread = null
        audioTrack?.stop()
        audioTrack?.flush()
        _currentBeat.value = 0
    }

    /**
     * Release resources.
     */
    fun release() {
        stop()
        audioTrack?.release()
        audioTrack = null
    }

    /**
     * Render the pattern to a float buffer (for export, not playback).
     * @param durationMs how long to render (will loop the pattern)
     */
    fun renderToBuffer(durationMs: Long): FloatArray {
        val pattern = currentPattern ?: return floatArrayOf()
        val totalSamples = (SAMPLE_RATE * durationMs / 1000.0).toInt()
        val buffer = FloatArray(totalSamples)

        val patternDurationSamples = (SAMPLE_RATE * pattern.durationMs / 1000.0).toInt()

        for (hit in pattern.hits) {
            val sampleData = samples[hit.sampleName] ?: continue
            val hitSample = (SAMPLE_RATE * hit.timeMs / 1000.0).toInt()

            // Render this hit for each loop
            var loopOffset = 0
            while (loopOffset < totalSamples) {
                val startSample = loopOffset + hitSample
                for (i in sampleData.indices) {
                    val idx = startSample + i
                    if (idx in buffer.indices) {
                        buffer[idx] += sampleData[i] * hit.velocity
                    }
                }
                loopOffset += patternDurationSamples
            }
        }

        // Clip to prevent distortion
        for (i in buffer.indices) {
            buffer[i] = buffer[i].coerceIn(-1f, 1f)
        }

        return buffer
    }

    private fun playLoop() {
        val track = audioTrack ?: return

        while (isPlaying) {
            val pattern = currentPattern ?: break
            val currentBpm = bpm
            val barDurationMs = (4 * 60_000.0 / currentBpm)
            val barDurationSamples = (SAMPLE_RATE * barDurationMs / 1000.0).toInt()

            // Render one bar
            val barBuffer = FloatArray(barDurationSamples)

            for (hit in pattern.hits) {
                val sampleData = samples[hit.sampleName] ?: continue
                // Recalculate hit time based on current BPM
                val hitRatio = hit.timeMs / pattern.durationMs
                val hitSample = (hitRatio * barDurationSamples).toInt()

                for (i in sampleData.indices) {
                    val idx = hitSample + i
                    if (idx in barBuffer.indices) {
                        barBuffer[idx] += sampleData[i] * hit.velocity
                    }
                }
            }

            // Clip
            for (i in barBuffer.indices) {
                barBuffer[i] = barBuffer[i].coerceIn(-1f, 1f)
            }

            // Write to AudioTrack in chunks
            val chunkSize = BUFFER_SIZE_FRAMES
            var offset = 0
            var beatCounter = 0
            val samplesPerBeat = barDurationSamples / 4

            while (offset < barBuffer.size && isPlaying) {
                val remaining = barBuffer.size - offset
                val writeSize = minOf(chunkSize, remaining)
                track.write(barBuffer, offset, writeSize, AudioTrack.WRITE_BLOCKING)
                offset += writeSize

                // Update beat counter
                val newBeat = (offset / samplesPerBeat).coerceAtMost(3)
                if (newBeat != beatCounter) {
                    beatCounter = newBeat
                    _currentBeat.value = beatCounter
                }
            }

            // Reset beat counter for next loop
            if (isPlaying) {
                _currentBeat.value = 0
            }
        }
    }
}
