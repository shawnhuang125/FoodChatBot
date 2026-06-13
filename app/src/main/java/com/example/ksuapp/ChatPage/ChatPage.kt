package com.example.ksuapp.ChatPage

import androidx.appcompat.app.AppCompatDelegate
import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.os.LocaleListCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.ksuapp.FavoritePage.FavoriteStorePage
import com.example.ksuapp.R
import com.example.ksuapp.Store_Data.StoreDataManager
import com.example.ksuapp.Store_Data.StoreDetailed
import com.example.ksuapp.Store_Data.StoreDetail
import com.example.ksuapp.scrollToBottom
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatPage(viewModel: ChatViewModel = viewModel()) {
    val panelBg = Color(0xFF2B292A)
    val inputBg = Color(0xFF141313)
    val sendBg = Color(0xFFE9E9E9)
    val sendFg = Color(0xFF1C1C1C)

    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    var shouldAutoScroll by remember { mutableStateOf(true) }
    val keyboardController = LocalSoftwareKeyboardController.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val context = LocalContext.current

    // 🚀 優化：監聽最後一則訊息的內容變動，達成即時逐字捲動
    val lastMessageContent = remember {
        derivedStateOf { viewModel.messages.lastOrNull()?.message?.lastOrNull()?.let { 
            if (it is text) it.content else if (it is storeCard) it.content else ""
        } ?: "" }
    }

    LaunchedEffect(listState) {
        snapshotFlow {
            val layoutInfo = listState.layoutInfo
            val totalItems = layoutInfo.totalItemsCount
            val lastVisible = layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
            val isScrolling = listState.isScrollInProgress
            
            // 🚀 智慧判定：
            // 1. 如果使用者正在手動捲動，則不強制改變自動捲動狀態（除非拉到底）
            // 2. 只有在使用者靠近底部（距離最後一項 1 個單位內）且沒有正在往上滑時，才開啟自動捲動
            if (isScrolling) {
                lastVisible >= totalItems - 1
            } else {
                lastVisible >= totalItems - 2 
            }
        }.collect { atBottom -> 
            if (atBottom) {
                shouldAutoScroll = true
            } else if (listState.isScrollInProgress) {
                // 如果使用者正在往上拉，就關閉自動捲動
                shouldAutoScroll = false
            }
        }
    }

    LaunchedEffect(viewModel.messages.size, lastMessageContent.value) {
        listState.scrollToBottom(viewModel.messages.size, scope, shouldAutoScroll)
    }

    Box(modifier = Modifier.fillMaxSize().background(panelBg).imePadding()) {
        if (viewModel.currentScreen == 0) {
            Column(modifier = Modifier.fillMaxSize().background(panelBg)) {
                // 🚀 動態狀態列背景：自動抓取手機真實狀態列高度並塗黑
                Spacer(
                    modifier = Modifier
                        .fillMaxWidth()
                        .windowInsetsTopHeight(WindowInsets.statusBars)
                        .background(Color.Black)
                )

                TitleBar(
                    onMenuClick = { viewModel.showMenu = true },
                    onNewClick = {
                        viewModel.resetChat()
                        scope.launch { listState.scrollToItem(0) }
                    }
                )

                LazyColumn(
                    state = listState,
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    contentPadding = PaddingValues(12.dp)
                ) {
                    // ... (保持不變)
                    items(viewModel.messages) { msg ->
                        if (msg.role == "user") {
                            MessageBubble(message = msg.message, isUser = true, onStoreClick = {})
                        } else if (msg.role == "assistant" && msg.message.isEmpty()) {
                            LoadingIndicator()
                        } else if (msg.role == "assistant") {
                            MessageBubble(
                                message = msg.message,
                                isUser = false,
                                onStoreClick = { segment ->
                                    if (segment is storeCard) {
                                        val pid = msg.pids.getOrNull(segment.index)
                                        if (pid != null) {
                                            val detail = StoreDataManager.findDetailById(pid)
                                            if (detail != null) {
                                                viewModel.selectedStore = StoreDetail(
                                                    pid = detail.id.toString(),
                                                    name = detail.name,
                                                    rating = detail.rating,
                                                    photos = detail.photos,
                                                    summary = segment.content,
                                                    description = detail.merchant_categories,
                                                    address = detail.address,
                                                    phone = detail.phone,
                                                    website = detail.website,
                                                    distance = detail.distance,
                                                    openingHours = detail.opening_hours,
                                                    facilityTags = detail.facility_tags,
                                                    attributesTags = detail.attributes_tags,
                                                    map_url = detail.map_url
                                                )
                                                viewModel.showDetail = true
                                            }
                                        }
                                    }
                                }
                            )
                        }
                    }
                }

                // 🚀 關鍵修改：只針對輸入框區域避開導航欄
                Box(modifier = Modifier.background(panelBg).navigationBarsPadding()) {
                    BottomInputBar(
                        inputBg = inputBg, sendBg = sendBg, sendFg = sendFg, text = viewModel.inputText, isChatDone = viewModel.isChatDone,
                        onTextChange = { viewModel.inputText = it },
                        onStop = { viewModel.stopStreaming() },
                        onSend = {
                            keyboardController?.hide()
                            viewModel.sendMessage(context)
                            scope.launch {
                                listState.animateScrollToItem(viewModel.messages.size - 1)
                                shouldAutoScroll = true
                            }
                        }
                    )
                }
            }
        } else if (viewModel.currentScreen == 1) {
            FavoriteStorePage(onBack = { viewModel.currentScreen = 0 })
        }

        AnimatedVisibility(
            visible = viewModel.showMenu && viewModel.currentScreen == 0,
            enter = slideInHorizontally(initialOffsetX = { -it }) + fadeIn(),
            exit = slideOutHorizontally(targetOffsetX = { -it }) + fadeOut()
        ) {
            Box(modifier = Modifier.fillMaxSize()) {
                Box(
                    modifier = Modifier.fillMaxSize()
                        .pointerInput(Unit) { detectTapGestures(onTap = { viewModel.showMenu = false }) }
                )

                // 🚀 側邊欄背景現在會真正填滿高度
                Column(
                    modifier = Modifier.fillMaxHeight().fillMaxWidth(0.7f).background(Color(0xFF1C1C1C)).padding(top = 60.dp)
                        .pointerInput(Unit) { detectTapGestures { } }
                ) {
                    MenuItem(text = stringResource(R.string.my_favorites)) {
                        viewModel.showMenu = false
                        viewModel.currentScreen = 1
                    }
                    
                    Spacer(modifier = Modifier.weight(1f))

                    Spacer(modifier = Modifier.navigationBarsPadding().height(24.dp))
                }
            }
        }

        if (viewModel.showDetail && viewModel.selectedStore != null) {
            ModalBottomSheet(
                onDismissRequest = { viewModel.showDetail = false },
                sheetState = sheetState,
                containerColor = Color(0xFF1C1C1C),
                dragHandle = null,
                properties = ModalBottomSheetProperties(shouldDismissOnBackPress = true)
            ) {
                StoreDetailed(store = viewModel.selectedStore!!, onClose = { viewModel.showDetail = false })
            }
        }
    }
}

@Composable
private fun MenuItem(text: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable { onClick() }.padding(horizontal = 24.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(text = text, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Medium)
    }
}
