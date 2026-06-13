package com.example.ksuapp.ChatPage

sealed interface MessageSegment

data class text(val content: String) : MessageSegment
data class storeCard(val content: String, val index: Int) : MessageSegment

data class ChatMessage(
    val role: String,
    val message: List<MessageSegment> = emptyList(),
    val pids: List<String> = emptyList()
)

data class WebSocketData(
    val text: String,
    val done: Boolean,
)
