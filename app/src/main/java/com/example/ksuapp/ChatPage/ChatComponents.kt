package com.example.ksuapp.ChatPage

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.decode.GifDecoder
import coil.request.ImageRequest
import com.example.ksuapp.R

@Composable
fun TitleBar(onMenuClick: () -> Unit, onNewClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().height(56.dp).background(Color.Black).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Icon(
            imageVector = Icons.Filled.Menu,
            contentDescription = stringResource(R.string.menu_title),
            tint = Color.White,
            modifier = Modifier.size(28.dp).clickable { onMenuClick() }
        )
        Row(
            modifier = Modifier.height(35.dp)
                .shadow(elevation = 4.dp, shape = RoundedCornerShape(28.dp))
                .background(color = Color(0xFF2E2B2C), shape = RoundedCornerShape(28.dp))
                .border(width = 1.1.dp, color = Color.White.copy(alpha = 0.24f), shape = RoundedCornerShape(28.dp))
                .clickable { onNewClick() }.padding(horizontal = 18.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(imageVector = Icons.Default.Delete, contentDescription = stringResource(R.string.refresh_chat), tint = Color.White, modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
fun BottomInputBar(
    inputBg: Color, sendBg: Color, sendFg: Color, text: String, isChatDone: Boolean,
    onTextChange: (String) -> Unit, onStop: () -> Unit, onSend: () -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth().padding(start = 16.dp, top = 8.dp, end = 16.dp, bottom = 16.dp)) {
        Spacer(modifier = Modifier.height(12.dp))
        Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
            Box(
                modifier = Modifier.fillMaxWidth().height(64.dp).clip(RoundedCornerShape(32.dp)).background(inputBg).padding(start = 20.dp, end = 72.dp),
                contentAlignment = Alignment.CenterStart
            ) {
                BasicTextField(value = text, onValueChange = onTextChange, singleLine = true, textStyle = TextStyle(color = Color.White, fontSize = 18.sp), modifier = Modifier.fillMaxWidth())
                if (text.isEmpty()) Text(text = stringResource(R.string.chat_input_placeholder), color = Color.White.copy(alpha = 0.7f), fontSize = 18.sp)
            }
            Box(
                modifier = Modifier.padding(end = 8.dp).size(48.dp).clip(CircleShape).background(sendBg)
                    .clickable { if (isChatDone) onSend() else onStop() },
                contentAlignment = Alignment.Center
            ) {
                if (isChatDone) Icon(imageVector = Icons.AutoMirrored.Filled.ArrowForward, contentDescription = "Send", tint = sendFg)
                else Box(modifier = Modifier.size(16.dp).background(sendFg, shape = RoundedCornerShape(2.dp)))
            }
        }
    }
}

@Composable
fun LoadingIndicator() {
    val infiniteTransition = rememberInfiniteTransition(label = "dots")
    val dotColor = Color.White.copy(alpha = 0.7f)
    
    Box(
        modifier = Modifier.fillMaxWidth().padding(start = 24.dp, top = 8.dp, bottom = 8.dp),
        contentAlignment = Alignment.CenterStart
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            modifier = Modifier
                .background(Color.White.copy(alpha = 0.08f), RoundedCornerShape(16.dp))
                .padding(horizontal = 16.dp, vertical = 14.dp)
        ) {
            repeat(3) { index ->
                // 🚀 建立上下跳動的動畫數值
                val yOffset by infiniteTransition.animateFloat(
                    initialValue = 0f,
                    targetValue = -10f, // 往上跳動 10 單位
                    animationSpec = infiniteRepeatable(
                        animation = tween(durationMillis = 400, easing = FastOutSlowInEasing),
                        repeatMode = RepeatMode.Reverse,
                        initialStartOffset = StartOffset(index * 150) // 產生波浪般的延遲感
                    ),
                    label = "dot_jump"
                )
                
                Box(
                    modifier = Modifier
                        .size(6.dp)
                        .graphicsLayer {
                            translationY = yOffset // 🚀 關鍵：套用垂直位移
                        }
                        .background(dotColor, CircleShape)
                )
            }
        }
    }
}
