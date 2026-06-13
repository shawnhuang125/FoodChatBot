package com.example.ksuapp

import androidx.compose.foundation.lazy.LazyListState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

fun LazyListState.scrollToBottom(
    messagesCount: Int,
    scope: CoroutineScope,
    shouldAutoScroll: Boolean
) {
    // 🚀 如果不應自動捲動，或正在手動操作中，則不執行
    if (!shouldAutoScroll || messagesCount <= 0 || isScrollInProgress) return

    scope.launch {
        // 使用 scrollToItem 確保即時性，但如果最後一個項目太長，
        // 這種方式會跳到該項目的頂部。在逐字輸出時，這是最穩定的做法。
        this@scrollToBottom.scrollToItem(messagesCount - 1)
    }
}
