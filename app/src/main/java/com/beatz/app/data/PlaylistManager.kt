package com.beatz.app.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Manages playlists stored as a JSON file.
 * Each playlist has a name and list of song directory names.
 * A song can be in multiple playlists.
 */
class PlaylistManager(private val filesDir: File) {

    private val file = File(filesDir, "playlists.json")

    fun getPlaylists(): Map<String, List<String>> {
        if (!file.exists()) return emptyMap()
        return try {
            val json = JSONObject(file.readText())
            val result = mutableMapOf<String, List<String>>()
            for (key in json.keys()) {
                val arr = json.getJSONArray(key)
                val songs = mutableListOf<String>()
                for (i in 0 until arr.length()) songs.add(arr.getString(i))
                result[key] = songs
            }
            result
        } catch (_: Exception) { emptyMap() }
    }

    fun createPlaylist(name: String) {
        val playlists = getPlaylists().toMutableMap()
        if (name !in playlists) {
            playlists[name] = emptyList()
            save(playlists)
        }
    }

    fun deletePlaylist(name: String) {
        val playlists = getPlaylists().toMutableMap()
        playlists.remove(name)
        save(playlists)
    }

    fun addSongToPlaylist(playlist: String, songDir: String) {
        val playlists = getPlaylists().toMutableMap()
        val songs = playlists[playlist]?.toMutableList() ?: mutableListOf()
        if (songDir !in songs) {
            songs.add(songDir)
            playlists[playlist] = songs
            save(playlists)
        }
    }

    fun removeSongFromPlaylist(playlist: String, songDir: String) {
        val playlists = getPlaylists().toMutableMap()
        val songs = playlists[playlist]?.toMutableList() ?: return
        songs.remove(songDir)
        playlists[playlist] = songs
        save(playlists)
    }

    fun moveSongInPlaylist(playlist: String, songDir: String, direction: Int) {
        val playlists = getPlaylists().toMutableMap()
        val songs = playlists[playlist]?.toMutableList() ?: return
        val index = songs.indexOf(songDir)
        if (index < 0) return
        val newIndex = (index + direction).coerceIn(0, songs.size - 1)
        if (newIndex == index) return
        songs.removeAt(index)
        songs.add(newIndex, songDir)
        playlists[playlist] = songs
        save(playlists)
    }

    fun getPlaylistsForSong(songDir: String): List<String> {
        return getPlaylists().filter { songDir in it.value }.keys.toList()
    }

    private fun save(playlists: Map<String, List<String>>) {
        val json = JSONObject()
        for ((name, songs) in playlists) {
            json.put(name, JSONArray(songs))
        }
        file.writeText(json.toString(2))
    }
}
