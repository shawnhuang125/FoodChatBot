package com.example.ksuapp.ChatPage

import android.annotation.SuppressLint
import android.content.Context
import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import com.example.ksuapp.AppLog
import com.example.ksuapp.Network.HttpClient
import com.example.ksuapp.Network.SocketClient
import com.example.ksuapp.Network.buildHttpRequestUrls
import com.example.ksuapp.Network.buildSocketRequest
import com.example.ksuapp.Store_Data.StoreDataManager
import com.example.ksuapp.Store_Data.StoreDetail
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority

import com.example.ksuapp.LocationHelper

class ChatViewModel : ViewModel() {

    private val MODULE = "ChatPage"

    var currentScreen by mutableIntStateOf(0)
    var inputText by mutableStateOf("")
    val messages = mutableStateListOf<ChatMessage>()
    var isChatDone by mutableStateOf(true)
    var httpSent by mutableStateOf(false)
    
    var showMenu by mutableStateOf(false)
    var showDetail by mutableStateOf(false)
    var selectedStore by mutableStateOf<StoreDetail?>(null)

    init {
        setupSocketListener()
        SocketClient.WebSocket_Connect()
    }

    private fun setupSocketListener() {
        SocketClient.onMessageReceived = { data ->
            if (data.done) {
                isChatDone = true
            }

            val pidList = SocketClient.getPid()
            if (!httpSent && !pidList.isNullOrEmpty()) {
                httpSent = true
                // 當收到 PID 時，同步更新最後一個助理訊息的 PIDs 清單
                val lastIndex = messages.lastIndex
                if (lastIndex >= 0 && messages[lastIndex].role == "assistant") {
                    messages[lastIndex] = messages[lastIndex].copy(pids = pidList)
                }
                buildHttpRequestUrls(LocationHelper.currentLat, LocationHelper.currentLng).forEach { HttpClient.send(it) }
            }

            val lastIndex = messages.lastIndex
            if (lastIndex >= 0 && messages[lastIndex].role == "assistant") {
                processAssistantMessage(data.text, messages[lastIndex], lastIndex)
            }
        }
    }

    private fun processAssistantMessage(raw: String, old: ChatMessage, index: Int) {
        val clean = raw.replace("<start>", "").replace("<end>", "")
        val lastSegment = old.message.lastOrNull()
        
        // 計算目前這則訊息中已經有多少個 storeCard 了
        val currentCardCount = old.message.count { it is storeCard }

        when {
            raw.contains("<start>") -> {
                messages[index] = old.copy(message = old.message + storeCard(clean, currentCardCount))
            }
            raw.contains("<end>") -> {
                if (lastSegment is storeCard) {
                    val updated = lastSegment.copy(content = lastSegment.content + clean)
                    messages[index] = old.copy(message = old.message.dropLast(1) + updated)
                }
            }
            else -> {
                if (lastSegment is storeCard) {
                    val updated = lastSegment.copy(content = lastSegment.content + clean)
                    messages[index] = old.copy(message = old.message.dropLast(1) + updated)
                } else if (lastSegment is text) {
                    val updated = lastSegment.copy(content = lastSegment.content + clean)
                    messages[index] = old.copy(message = old.message.dropLast(1) + updated)
                } else {
                    messages[index] = old.copy(message = old.message + text(clean))
                }
            }
        }
        StoreDataManager.onSummaryTextReceived(raw)
    }

    @SuppressLint("MissingPermission")
    fun sendMessage(context: Context) {
        val t = inputText.trim()
        if (t.isEmpty()) return
        
        inputText = ""
        httpSent = false
        StoreDataManager.resetSummary()

        messages.add(ChatMessage(role = "user", message = listOf(text(t))))
        isChatDone = false
        messages.add(ChatMessage(role = "assistant", message = emptyList()))

        sendToSocket(t)
    }

    private fun sendToSocket(query: String) {
        val requestJson = buildSocketRequest(query, LocationHelper.currentLat, LocationHelper.currentLng)
        AppLog.i("資料內容：$requestJson | 傳送到 WebSocket", MODULE)
        
        if (SocketClient.isConnected) {
            SocketClient.send(requestJson)
        }
    }


    fun stopStreaming() {
        isChatDone = true
        SocketClient.stopStreaming()
        if (messages.lastOrNull()?.role == "assistant" && messages.lastOrNull()?.message?.isEmpty() == true) {
            messages.removeAt(messages.lastIndex)
        }
    }

    fun resetChat() {
        messages.clear()
        SocketClient.CommandClear()
        StoreDataManager.clearDetails()
        StoreDataManager.resetSummary()
        httpSent = false
        isChatDone = true
    }
}
