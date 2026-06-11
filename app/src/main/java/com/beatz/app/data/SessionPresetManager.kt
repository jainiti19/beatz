package com.beatz.app.data

import org.json.JSONObject
import java.io.File

/**
 * A session preset stores all jamming settings for a (song, playlist) combination.
 */
data class SessionPreset(
    val startPosition: Float = 0f,        // 0.0 - 1.0 fraction
    val stemVolumes: Map<String, Float> = emptyMap(),
    val speed: Float = 1.0f,
    val loopEnabled: Boolean = false,
    val loopStart: Float = 0f,
    val loopEnd: Float = 1f,
    val tagName: String = ""              // e.g. "Chorus", "Bridge", "Hook"
)

/**
 * Manages session presets stored as JSON.
 * Key: "playlistName::songDirName" (or "all::songDirName" for non-playlist)
 */
class SessionPresetManager(private val filesDir: File) {

    private val file = File(filesDir, "session_presets.json")

    private fun key(playlist: String?, songDir: String): String {
        return "${playlist ?: "all"}::$songDir"
    }

    fun getPreset(playlist: String?, songDir: String): SessionPreset? {
        val all = loadAll()
        val json = all.optJSONObject(key(playlist, songDir)) ?: return null
        return parsePreset(json)
    }

    fun savePreset(playlist: String?, songDir: String, preset: SessionPreset) {
        val all = loadAll()
        all.put(key(playlist, songDir), presetToJson(preset))
        file.writeText(all.toString(2))
    }

    fun deletePreset(playlist: String?, songDir: String) {
        val all = loadAll()
        all.remove(key(playlist, songDir))
        file.writeText(all.toString(2))
    }

    fun hasPreset(playlist: String?, songDir: String): Boolean {
        return loadAll().has(key(playlist, songDir))
    }

    private fun loadAll(): JSONObject {
        if (!file.exists()) return JSONObject()
        return try { JSONObject(file.readText()) } catch (_: Exception) { JSONObject() }
    }

    private fun parsePreset(json: JSONObject): SessionPreset {
        val volumes = mutableMapOf<String, Float>()
        val volJson = json.optJSONObject("stemVolumes")
        if (volJson != null) {
            for (k in volJson.keys()) {
                volumes[k] = volJson.getDouble(k).toFloat()
            }
        }
        return SessionPreset(
            startPosition = json.optDouble("startPosition", 0.0).toFloat(),
            stemVolumes = volumes,
            speed = json.optDouble("speed", 1.0).toFloat(),
            loopEnabled = json.optBoolean("loopEnabled", false),
            loopStart = json.optDouble("loopStart", 0.0).toFloat(),
            loopEnd = json.optDouble("loopEnd", 1.0).toFloat(),
            tagName = json.optString("tagName", "")
        )
    }

    private fun presetToJson(preset: SessionPreset): JSONObject {
        val json = JSONObject()
        json.put("startPosition", preset.startPosition.toDouble())
        val volJson = JSONObject()
        for ((k, v) in preset.stemVolumes) {
            volJson.put(k, v.toDouble())
        }
        json.put("stemVolumes", volJson)
        json.put("speed", preset.speed.toDouble())
        json.put("loopEnabled", preset.loopEnabled)
        json.put("loopStart", preset.loopStart.toDouble())
        json.put("loopEnd", preset.loopEnd.toDouble())
        json.put("tagName", preset.tagName)
        return json
    }
}
