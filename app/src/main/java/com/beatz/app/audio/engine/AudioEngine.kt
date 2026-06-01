package com.beatz.app.audio.engine

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import com.beatz.app.data.model.BeatPattern
import com.beatz.app.data.model.Layer
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Core audio engine using Android's AudioTrack API.
 * Supports multiple layers (instruments) mixed together.
 */
class AudioEngine {

    companion object {
        const val SAMPLE_RATE = 44100
        private const val BUFFER_SIZE_FRAMES = 1024
    }

    private var audioTrack: AudioTrack? = null
    private var playbackThread: Thread? = null
    private var samples: MutableMap<String, FloatArray> = mutableMapOf()

    // Multi-layer support: each layer has its own pattern
    @Volatile
    private var layerPatterns: Map<String, LayerPlayback> = emptyMap()

    @Volatile
    private var isPlaying = false

    @Volatile
    private var bpm: Float = 120f

    private val _currentBeat = MutableStateFlow(0)
    val currentBeat: StateFlow<Int> = _currentBeat

    private val _playbackState = MutableStateFlow(PlaybackState.STOPPED)
    val playbackState: StateFlow<PlaybackState> = _playbackState

    enum class PlaybackState { PLAYING, PAUSED, STOPPED }

    data class LayerPlayback(
        val pattern: BeatPattern,
        val volume: Float,
        val isMuted: Boolean
    )

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
     * Set a single layer's pattern and playback settings.
     */
    fun setLayerPattern(layer: Layer, pattern: BeatPattern) {
        ensureSamplesLoaded(pattern)
        val hasSolo = layerPatterns.values.any { it !== layerPatterns[layer.id] && !it.isMuted } &&
                layerPatterns.values.any { it.isMuted }
        layerPatterns = layerPatterns + (layer.id to LayerPlayback(
            pattern = pattern,
            volume = layer.volume,
            isMuted = layer.isMuted
        ))
        bpm = pattern.bpm
    }

    /**
     * Update all layers at once (used when solo/mute/volume changes).
     */
    fun updateLayers(layers: List<Layer>, patterns: Map<String, BeatPattern>) {
        val anySolo = layers.any { it.isSolo }
        val newMap = mutableMapOf<String, LayerPlayback>()
        for (layer in layers) {
            val pattern = patterns[layer.id] ?: continue
            ensureSamplesLoaded(pattern)
            val effectiveMute = if (anySolo) !layer.isSolo else layer.isMuted
            newMap[layer.id] = LayerPlayback(
                pattern = pattern,
                volume = layer.volume,
                isMuted = effectiveMute
            )
        }
        layerPatterns = newMap
    }

    /**
     * Remove a layer.
     */
    fun removeLayer(layerId: String) {
        layerPatterns = layerPatterns - layerId
    }

    /**
     * Backwards-compatible: set a single pattern (used by Phase 1 code).
     */
    fun setPattern(pattern: BeatPattern) {
        ensureSamplesLoaded(pattern)
        layerPatterns = mapOf("default" to LayerPlayback(pattern, 0.8f, false))
        bpm = pattern.bpm
    }

    private fun ensureSamplesLoaded(pattern: BeatPattern) {
        for (hit in pattern.hits) {
            if (hit.sampleName !in samples) {
                val generated = generatePitchedSample(hit.sampleName)
                if (generated != null) {
                    samples[hit.sampleName] = generated
                }
            }
        }
    }

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
                val parts = name.removePrefix("flute_").split("_")
                val midi = parts.getOrNull(0)?.toIntOrNull() ?: return null
                val isLong = parts.getOrNull(1) != "short"
                SampleGenerator.generateFluteNote(midi, isLong)
            }
            else -> null
        }
    }

    fun getSampleCount(): Int = samples.size

    fun setBpm(newBpm: Float) {
        bpm = newBpm
    }

    fun play() {
        if (layerPatterns.isEmpty() || isPlaying) return

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
        _currentBeat.value = 0
    }

    fun release() {
        stop()
        audioTrack?.release()
        audioTrack = null
    }

    /**
     * Render all layers mixed together to a buffer (for export).
     */
    fun renderToBuffer(durationMs: Long): FloatArray {
        val layers = layerPatterns.values.toList()
        if (layers.isEmpty()) return floatArrayOf()

        val totalSamples = (SAMPLE_RATE * durationMs / 1000.0).toInt()
        val buffer = FloatArray(totalSamples)

        for (lp in layers) {
            if (lp.isMuted) continue
            val pattern = lp.pattern
            val patternDurationSamples = (SAMPLE_RATE * pattern.durationMs / 1000.0).toInt()

            for (hit in pattern.hits) {
                val sampleData = samples[hit.sampleName] ?: continue
                val hitSample = (SAMPLE_RATE * hit.timeMs / 1000.0).toInt()

                var loopOffset = 0
                while (loopOffset < totalSamples) {
                    val startSample = loopOffset + hitSample
                    for (i in sampleData.indices) {
                        val idx = startSample + i
                        if (idx in buffer.indices) {
                            buffer[idx] += sampleData[i] * hit.velocity * lp.volume
                        }
                    }
                    loopOffset += patternDurationSamples
                }
            }
        }

        for (i in buffer.indices) {
            buffer[i] = buffer[i].coerceIn(-1f, 1f)
        }

        return buffer
    }

    private fun playLoop() {
        val track = audioTrack ?: return

        while (isPlaying) {
            val layers = layerPatterns.values.toList()
            if (layers.isEmpty()) break

            val currentBpm = bpm
            val barDurationMs = (4 * 60_000.0 / currentBpm)
            val barDurationSamples = (SAMPLE_RATE * barDurationMs / 1000.0).toInt()

            // Render one bar mixing all layers
            val barBuffer = FloatArray(barDurationSamples)

            for (lp in layers) {
                if (lp.isMuted) continue
                val pattern = lp.pattern

                for (hit in pattern.hits) {
                    val sampleData = samples[hit.sampleName] ?: continue
                    val hitRatio = hit.timeMs / pattern.durationMs
                    val hitSample = (hitRatio * barDurationSamples).toInt()

                    for (i in sampleData.indices) {
                        val idx = hitSample + i
                        if (idx in barBuffer.indices) {
                            barBuffer[idx] += sampleData[i] * hit.velocity * lp.volume
                        }
                    }
                }
            }

            for (i in barBuffer.indices) {
                barBuffer[i] = barBuffer[i].coerceIn(-1f, 1f)
            }

            val chunkSize = BUFFER_SIZE_FRAMES
            var offset = 0
            var beatCounter = 0
            val samplesPerBeat = barDurationSamples / 4

            while (offset < barBuffer.size && isPlaying) {
                val remaining = barBuffer.size - offset
                val writeSize = minOf(chunkSize, remaining)
                track.write(barBuffer, offset, writeSize, AudioTrack.WRITE_BLOCKING)
                offset += writeSize

                val newBeat = (offset / samplesPerBeat).coerceAtMost(3)
                if (newBeat != beatCounter) {
                    beatCounter = newBeat
                    _currentBeat.value = beatCounter
                }
            }

            if (isPlaying) {
                _currentBeat.value = 0
            }
        }
    }
}
