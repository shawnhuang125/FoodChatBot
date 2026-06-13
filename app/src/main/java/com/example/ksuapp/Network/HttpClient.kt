package com.example.ksuapp.Network

import com.example.ksuapp.AppLog
import com.example.ksuapp.Store_Data.StoreDataManager
import com.example.ksuapp.Store_Data.StoreDetailData
import okhttp3.*
import org.json.JSONObject
import java.io.IOException

object HttpClient {

    private const val MODULE = "Http"
    private val client = OkHttpClient()

    fun send(url: String) {
        val request = Request.Builder().url(url).get().build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                AppLog.e("Http: 請求失敗 ($url) | 錯誤：${e.message}", e, MODULE)
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                AppLog.i("資料內容：$body | 來源：伺服器回應 ($url)", MODULE)

                try {
                    val json = JSONObject(body)
                    if (json.optString("status") == "success") {
                        val detail = parseStoreDetail(json.getJSONObject("data"))
                        AppLog.i("資料內容：Store(id=${detail.id}, name=${detail.name}) | 傳送到 StoreDataManager", MODULE)
                        StoreDataManager.upsertDetail(detail)
                    }
                } catch (e: Exception) {
                    AppLog.e("Http: 解析失敗", e, MODULE)
                }
            }
        })
    }

    private fun parseStoreDetail(json: JSONObject): StoreDetailData {
        val openingMap = mutableMapOf<String, String>()
        val openingJson = json.optJSONObject("opening_hours")
        openingJson?.keys()?.forEach { openingMap[it] = openingJson.getString(it) }

        val photosArr = json.optJSONArray("photos")
        val photosList = if (photosArr != null) List(photosArr.length()) { photosArr.getString(it) } else emptyList()

        val facilityArr = json.optJSONArray("facility_tags")
        val facilityList = if (facilityArr != null) List(facilityArr.length()) { facilityArr.getString(it) } else emptyList()

        val attributesArr = json.optJSONArray("attributes_tags")
        val attributesList = if (attributesArr != null) List(attributesArr.length()) { attributesArr.getString(it) } else emptyList()

        return StoreDetailData(
            id = json.optInt("id", 0),
            name = json.optString("name", "未知店家"),
            address = json.optString("address", "地址不詳"),
            phone = json.optString("phone", "電話不詳"),
            rating = json.optDouble("rating", 0.0),
            website = json.optString("website", ""),
            distance = json.optString("distance", ""),
            facility_tags = facilityList,
            attributes_tags = attributesList,
            merchant_categories = json.optString("merchant_categories", ""),
            opening_hours = openingMap,
            map_url = json.optString("map_url", ""),
            photos = photosList
        )
    }
}

fun buildHttpRequestUrls(lat: Double, lng: Double): List<String> {
    val sid = SocketClient.getSid() ?: return emptyList()
    val pidlist = SocketClient.getPid() ?: return emptyList()
    val formattedLat = String.format(java.util.Locale.US, "%.7f", lat)
    val formattedLng = String.format(java.util.Locale.US, "%.7f", lng)

    return pidlist.map { pid ->
        /* "http://192.168.1.112:5003/get_place_info/$pid?sid=$sid&user_lat=$formattedLat&user_lng=$formattedLng" // IP Address */


        "https://uncramped-flynn-basined.ngrok-free.dev/get_place_info/$pid?sid=$sid&user_lat=$formattedLat&user_lng=$formattedLng" // IP Address
    }


}
