package com.example.ksuapp.ChatPage

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.ksuapp.Store_Data.StoreSummaryCard

@Composable
fun MessageBubble(
    message: List<MessageSegment>,
    isUser: Boolean,
    onStoreClick: (MessageSegment) -> Unit
) {
    val screenWidth = LocalConfiguration.current.screenWidthDp.dp
    val maxBubbleWidth = screenWidth * 0.85f

    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = if (isUser) Alignment.CenterEnd else Alignment.CenterStart
    ) {
        Box(
            modifier = Modifier
                .padding(vertical = 6.dp, horizontal = 12.dp)
                .widthIn(max = maxBubbleWidth)
                .background(
                    color = if (isUser) {
                        Color(0xFF3D3D3D)
                    } else {
                        Color.White.copy(alpha = 0.08f)
                    },
                    shape = RoundedCornerShape(
                        topStart = if (isUser) 16.dp else 4.dp,
                        topEnd = if (isUser) 4.dp else 16.dp,
                        bottomStart = 16.dp,
                        bottomEnd = 16.dp
                    )
                )
                .border(
                    width = 0.5.dp,
                    color = if (isUser) Color.Transparent else Color.White.copy(alpha = 0.12f),
                    shape = RoundedCornerShape(
                        topStart = if (isUser) 16.dp else 4.dp,
                        topEnd = if (isUser) 4.dp else 16.dp,
                        bottomStart = 16.dp,
                        bottomEnd = 16.dp
                    )
                )
                .padding(vertical = 12.dp, horizontal = 16.dp)
        ) {
            // 🚀 方案 A：在泡泡內部開啟文字選取與複製
            SelectionContainer {
                Column {
                    message.forEach { segment ->
                        when (segment) {
                            is text -> {
                                Text(
                                    text = segment.content,
                                    color = if (isUser) Color.White else Color(0xFFE0E0E0),
                                    fontSize = 16.sp,
                                    lineHeight = 24.sp,
                                    letterSpacing = 0.5.sp
                                )
                            }
                            is storeCard -> {
                                StoreSummaryCard(
                                    text = segment.content,
                                    onClick = { onStoreClick(segment) }
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
