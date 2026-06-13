package com.example.ksuapp.Network

import android.os.Handler
import android.os.Looper
import com.example.ksuapp.AppLog
import com.example.ksuapp.ChatPage.WebSocketData
import com.example.ksuapp.Store_Data.StoreDataManager
import io.socket.client.IO
import io.socket.client.Socket
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

object SocketClient {

    var isConnected: Boolean = false
    /*private const val IP = "http://192.168.1.113:5000" // IP Address */

    private const val IP = "https://uncramped-flynn-basined.ngrok-free.dev" // IP Address

    private const val MODULE = "Websocket"

    var onMessageReceived: ((WebSocketData) -> Unit)? = null

    private var socket: Socket? = null
    private var socketID: String? = null
    private var storePID: List<String>? = null

    private val mainHandler = Handler(Looper.getMainLooper())
    private var retryRunnable: Runnable? = null
    private var reConnectState = false

    fun WebSocket_Connect() {
        if (socket != null) return

        val options = IO.Options().apply {
            path = "/socket.io"
            transports = arrayOf("websocket")
        }
        socket = IO.socket(IP, options)
        socket?.connect()

        socket?.on(Socket.EVENT_CONNECT) {
            socketID = socket?.id()
            isConnected = true
            AppLog.i("WebSocket: 已連線 (SID=$socketID)", MODULE)
            stopReConnect()
        }

        socket?.on(Socket.EVENT_CONNECT_ERROR) { args ->
            isConnected = false
            AppLog.e("連線失敗", null, MODULE)
            startReConnect()
        }

        socket?.on(Socket.EVENT_DISCONNECT) {
            isConnected = false
            AppLog.w("連線已中斷", MODULE)
            startReConnect()
        }

        socket?.on("chat_stream") { args ->
            mainHandler.post {
                try {
                    val data = args.firstOrNull() as? JSONObject ?: return@post
                    
                    val pidlist = parsePid(data)
                    if (pidlist != null) {
                        storePID = pidlist
                        AppLog.i("資料內容：$pidlist | 傳送到 StoreDataManager", MODULE)
                        return@post
                    }

                    val serverData = dataProcessing(data)
                    AppLog.i("資料內容：${serverData.text} | 傳送到 ChatPage (done=${serverData.done})", MODULE)

                    StoreDataManager.onSummaryTextReceived(serverData.text)
                    onMessageReceived?.invoke(WebSocketData(serverData.text, serverData.done))
                } catch (e: Exception) {
                    AppLog.e("WebSocket: 解析錯誤", e, MODULE)
                }
            }
        }
    }

    fun send(jsonString: String) {
        if (socket?.connected() != true) return
        val json = JSONObject(jsonString)
        socket?.emit("text_input", json)
    }

    fun disconnect() {
        socket?.disconnect()
        socket?.off()
        socket = null
        isConnected = false
    }

    private fun startReConnect() {
        if (reConnectState) return
        reConnectState = true
        retryRunnable = object : Runnable {
            override fun run() {
                if (socket == null || socket?.connected() == true) {
                    stopReConnect()
                    return
                }
                AppLog.w("嘗試重新建立連線", MODULE)
                socket?.connect()
                mainHandler.postDelayed(this, 5000)
            }
        }
        mainHandler.postDelayed(retryRunnable!!, 5000)
    }

    private fun stopReConnect() {
        reConnectState = false
        retryRunnable?.let { mainHandler.removeCallbacks(it) }
        retryRunnable = null
    }

    private fun parsePid(raw: JSONObject): List<String>? {
        if (!raw.has("pid")) return null
        val arr = raw.getJSONArray("pid")
        return List(arr.length()) { i -> arr.getString(i) }
    }

    fun getSid(): String? = socketID
    fun getPid(): List<String>? = storePID

    fun stopStreaming() {
        if (socket?.connected() == true) {
            val json = JSONObject().apply { put("action", "stop") }
            AppLog.i("資料內容：$json | 傳送到 伺服器", MODULE)
            socket?.emit("text_input", json)
        }
    }

    fun CommandClear() {
        if (socket?.connected() == true) {
            val json = JSONObject().apply { put("action", "reset") }
            AppLog.i("資料內容：$json | 傳送到 伺服器", MODULE)
            socket?.emit("text_input", json)
        }
    }
}

fun dataProcessing(data: Any?): WebSocketData {
    val obj = when (data) {
        is JSONObject -> data
        is String -> JSONObject(data)
        else -> JSONObject(data?.toString() ?: "{}")
    }
    return WebSocketData(text = obj.optString("text", ""), done = obj.optBoolean("done", false))
}

fun buildSocketRequest(user_input_text: String, lat: Double, lng: Double): String {
    val taipeiTime = LocalDateTime.now(ZoneId.of("Asia/Taipei"))
    val formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
    val dayOfWeekFormatter = DateTimeFormatter.ofPattern("EEEE", java.util.Locale.TAIWAN)
    val formattedLat = String.format(java.util.Locale.US, "%.7f", lat)
    val formattedLng = String.format(java.util.Locale.US, "%.7f", lng)

    val map = mapOf(
        "role" to "user",
        "text" to user_input_text,
        "time" to "${taipeiTime.format(dayOfWeekFormatter)} ${taipeiTime.format(formatter)}",
        "gps" to mapOf("lat" to formattedLat, "lng" to formattedLng)
    )
    return JSONObject(map).toString()
}
