package com.example.ksuapp

import android.Manifest
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import com.example.ksuapp.ChatPage.ChatPage
import com.example.ksuapp.ui.theme.KSUAPPTheme

class MainActivity : AppCompatActivity() {

    private val locationPermissionRequest = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        when {
            permissions.getOrDefault(Manifest.permission.ACCESS_FINE_LOCATION, false) -> {
                LocationHelper.startListening(this)
            }
            permissions.getOrDefault(Manifest.permission.ACCESS_COARSE_LOCATION, false) -> {
                LocationHelper.startListening(this)
            }
            else -> {
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // 🚀 移除原本強制 Night Mode 的指令，改由 Theme 內部邏輯控制顏色一致性

        enableEdgeToEdge()

        // 🚀 初始化收藏夾資料庫
        com.example.ksuapp.FavoritePage.FavoriteManager.init(this)

        // 啟動時請求定位權限
        locationPermissionRequest.launch(arrayOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION
        ))

        setContent {
            KSUAPPTheme {
                ChatPage()
            }
        }
    }
}
