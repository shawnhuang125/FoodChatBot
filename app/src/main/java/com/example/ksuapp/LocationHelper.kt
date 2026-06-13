package com.example.ksuapp

import android.annotation.SuppressLint
import android.content.Context
import android.os.Looper
import com.google.android.gms.location.*

object LocationHelper {

    private const val MODULE = "Location"
    private var fusedLocationClient: FusedLocationProviderClient? = null
    
    // 全域快取位置
    var currentLat: Double = 0.0
        private set
    var currentLng: Double = 0.0
        private set

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(locationResult: LocationResult) {
            val location = locationResult.lastLocation ?: return
            currentLat = location.latitude
            currentLng = location.longitude
        }
    }

    @SuppressLint("MissingPermission")
    fun startListening(context: Context) {
        if (fusedLocationClient != null) return

        fusedLocationClient = LocationServices.getFusedLocationProviderClient(context)
        
        // 設定 8秒 / 8公尺
        val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 8000)
            .setMinUpdateDistanceMeters(8f)
            .build()

        fusedLocationClient?.requestLocationUpdates(
            locationRequest,
            locationCallback,
            Looper.getMainLooper()
        )
        
        // 同步嘗試獲取最後已知位置作為初始值
        fusedLocationClient?.lastLocation?.addOnSuccessListener { location ->
            if (location != null) {
                currentLat = location.latitude
                currentLng = location.longitude
            }
        }
        
        AppLog.i("啟動 8秒/8公尺 定位監聽系統", MODULE)
    }

    fun stopListening() {
        fusedLocationClient?.removeLocationUpdates(locationCallback)
        fusedLocationClient = null
        AppLog.i("動作：已停止定位監聽系統", MODULE)
    }
}
