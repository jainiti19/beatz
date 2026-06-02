package com.beatz.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Scaffold
import androidx.compose.ui.Modifier
import com.beatz.app.ui.navigation.BeatzNavGraph
import com.beatz.app.ui.theme.BeatzTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val testFilePath = intent.getStringExtra("test_file")
        val jammingStemDir = intent.getStringExtra("stem_dir")

        setContent {
            BeatzTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    BeatzNavGraph(
                        testFilePath = testFilePath,
                        jammingStemDir = jammingStemDir
                    )
                }
            }
        }
    }
}
