package com.example.ksuapp.FavoritePage

import android.content.ClipData
import android.content.ClipDescription
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.draganddrop.dragAndDropSource
import androidx.compose.foundation.draganddrop.dragAndDropTarget
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draganddrop.DragAndDropEvent
import androidx.compose.ui.draganddrop.DragAndDropTarget
import androidx.compose.ui.draganddrop.DragAndDropTransferData
import androidx.compose.ui.draganddrop.toAndroidDragEvent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.ksuapp.R
import com.example.ksuapp.Store_Data.StoreDetailed
import kotlin.math.roundToInt

@Composable
fun getIconByName(name: String): ImageVector {
    return when (name) {
        "Favorite" -> Icons.Default.Favorite
        "Star" -> Icons.Default.Star
        "Home" -> Icons.Default.Home
        "Restaurant" -> Icons.Default.Restaurant
        "LocalDrink" -> Icons.Default.LocalDrink
        "ShoppingCart" -> Icons.Default.ShoppingCart
        "Store" -> Icons.Default.Store
        else -> Icons.Default.Folder
    }
}

val availableIcons = listOf("Folder", "Favorite", "Star", "Home", "Restaurant", "LocalDrink", "ShoppingCart", "Store")
val availableColors = listOf("#66BB6A", "#FF5252", "#64B5F6", "#FFD740", "#BA68C8", "#FF9800", "#90A4AE")

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun FavoriteStorePage(
    onBack: () -> Unit,
    viewModel: FavoriteViewModel = viewModel()
) {
    val foldersWithStores by viewModel.folders.collectAsState()
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val panelBg = Color(0xFF2B292A) // 取得 ChatPage 同款底色

    Box(modifier = Modifier.fillMaxSize().background(panelBg).navigationBarsPadding()) {
        if (!viewModel.isSearchMode) {
            Column(modifier = Modifier.fillMaxSize()) {
                Box(modifier = Modifier.fillMaxWidth().padding(top = 48.dp, bottom = 8.dp).height(56.dp)) {
                    IconButton(onClick = onBack, modifier = Modifier.align(Alignment.CenterStart).padding(start = 8.dp)) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back", tint = Color.White)
                    }
                    Text(text = stringResource(R.string.my_favorites), color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.align(Alignment.Center))
                }

                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    foldersWithStores.forEach { item ->
                        val folder = item.folder
                        val stores = item.stores
                        val isExpanded = viewModel.expandedStates[folder.name] ?: true
                        val isFolderHovering = viewModel.hoveringFolders[folder.id] ?: false

                        item(key = "header_${folder.id}") {
                            val dndTarget = remember(folder) {
                                object : DragAndDropTarget {
                                    override fun onDrop(event: DragAndDropEvent): Boolean {
                                        viewModel.setFolderHovering(folder.id, false)
                                        val text = event.toAndroidDragEvent().clipData?.getItemAt(0)?.text?.toString() ?: return false
                                        viewModel.moveStore(pid = text, toFolderId = folder.id)
                                        return true
                                    }
                                    override fun onEntered(event: DragAndDropEvent) { viewModel.setFolderHovering(folder.id, true) }
                                    override fun onExited(event: DragAndDropEvent) { viewModel.setFolderHovering(folder.id, false) }
                                    override fun onEnded(event: DragAndDropEvent) { viewModel.setFolderHovering(folder.id, false) }
                                }
                            }

                            FolderHeaderItem(
                                folder = folder,
                                storeCount = stores.size,
                                isExpanded = isExpanded,
                                isHovering = isFolderHovering,
                                dndTarget = dndTarget,
                                onToggle = { viewModel.toggleFolder(folder.name) },
                                onDelete = { viewModel.removeFolder(folder) }
                            )
                        }

                        if (isExpanded) {
                            items(stores, key = { "store_${it.pid}_${folder.id}" }) { store ->
                                FavoriteStoreItem(
                                    storeName = store.name,
                                    pid = store.pid,
                                    isHovering = isFolderHovering,
                                    dndTarget = null,
                                    onClick = { viewModel.loadStoreDetail(store.pid, store.name) }
                                )
                            }
                        }
                    }
                }
            }
        } else {
            Column(modifier = Modifier.fillMaxSize()) {
                Box(modifier = Modifier.fillMaxWidth().padding(top = 48.dp).height(56.dp), contentAlignment = Alignment.CenterStart) {
                    IconButton(onClick = { viewModel.isSearchMode = false; viewModel.searchQuery = "" }, modifier = Modifier.padding(start = 8.dp)) {
                        Icon(Icons.Default.Close, contentDescription = "Close Search", tint = Color.White)
                    }
                    TextField(
                        value = viewModel.searchQuery,
                        onValueChange = { viewModel.searchQuery = it },
                        placeholder = { Text(stringResource(R.string.search_favorites), color = Color.Gray) },
                        colors = TextFieldDefaults.colors(
                            focusedContainerColor = Color.Transparent,
                            unfocusedContainerColor = Color.Transparent,
                            focusedTextColor = Color.White,
                            unfocusedTextColor = Color.White,
                            focusedIndicatorColor = Color.Transparent,
                            unfocusedIndicatorColor = Color.Transparent
                        ),
                        modifier = Modifier.fillMaxWidth().padding(start = 56.dp, end = 16.dp),
                        singleLine = true
                    )
                }
                
                HorizontalDivider(color = Color.White.copy(alpha = 0.3f))

                LazyColumn(modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    val results = viewModel.searchResults.value
                    if (results.isEmpty() && viewModel.searchQuery.isNotBlank()) {
                        item {
                            Text(stringResource(R.string.no_matching_stores), color = Color.Gray, modifier = Modifier.padding(16.dp).fillMaxWidth(), textAlign = TextAlign.Center)
                        }
                    }
                    items(results) { store ->
                        FavoriteStoreItem(
                            storeName = store.name,
                            pid = store.pid,
                            isHovering = false,
                            dndTarget = null,
                            onClick = { viewModel.loadStoreDetail(store.pid, store.name) }
                        )
                    }
                }
            }
        }

        if (!viewModel.isSearchMode) {
            Box(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 32.dp, start = 16.dp, end = 16.dp)
                    .fillMaxWidth()
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Surface(
                        onClick = { viewModel.isSearchMode = true },
                        modifier = Modifier
                            .weight(1f)
                            .height(56.dp),
                        shape = RoundedCornerShape(28.dp),
                        color = Color(0xFF1C1C1C), // 改用較深的顏色，增加對比感
                        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.2f)) // 增加線條透明度
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(horizontal = 20.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Default.Search,
                                contentDescription = null,
                                tint = Color.White.copy(alpha = 0.7f),
                                modifier = Modifier.size(20.dp)
                            )
                            Spacer(modifier = Modifier.width(12.dp))
                            Text(
                                text = stringResource(R.string.search_favorites),
                                color = Color.White.copy(alpha = 0.5f),
                                fontSize = 16.sp
                            )
                        }
                    }

                    FloatingActionButton(
                        onClick = { viewModel.showDialog = true },
                        containerColor = Color(0xFF3B5BDB), 
                        contentColor = Color.White,
                        shape = CircleShape,
                        modifier = Modifier.size(56.dp),
                        elevation = FloatingActionButtonDefaults.elevation(4.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Add,
                            contentDescription = "Add List",
                            modifier = Modifier.size(28.dp)
                        )
                    }
                }
            }
        }

        if (viewModel.showDetail && viewModel.selectedStore != null) {
            ModalBottomSheet(onDismissRequest = { viewModel.showDetail = false }, sheetState = sheetState, containerColor = Color(0xFF1C1C1C), dragHandle = null) {
                Box(modifier = Modifier.navigationBarsPadding()) {
                    StoreDetailed(store = viewModel.selectedStore!!, onClose = { viewModel.showDetail = false })
                }
            }
        }

        if (viewModel.showDialog) {
            AlertDialog(
                onDismissRequest = { viewModel.showDialog = false; viewModel.resetDialogState() },
                title = { Text(stringResource(R.string.add_category), color = Color.White) },
                text = {
                    Column {
                        TextField(
                            value = viewModel.newFolderName,
                            onValueChange = { viewModel.newFolderName = it },
                            placeholder = { Text(stringResource(R.string.category_name), color = Color.Gray) },
                            colors = TextFieldDefaults.colors(
                                focusedTextColor = Color.White,
                                unfocusedTextColor = Color.White,
                                focusedContainerColor = Color(0xFF2B292A),
                                unfocusedContainerColor = Color(0xFF2B292A)
                            ),
                            modifier = Modifier.fillMaxWidth()
                        )
                        
                        Spacer(modifier = Modifier.height(16.dp))
                        Text(stringResource(R.string.select_icon), color = Color.Gray, fontSize = 14.sp)
                        LazyRow(modifier = Modifier.padding(vertical = 8.dp)) {
                            items(availableIcons) { iconName ->
                                val isSelected = viewModel.selectedIconName == iconName
                                Box(
                                    modifier = Modifier
                                        .size(40.dp)
                                        .padding(4.dp)
                                        .background(
                                            if (isSelected) Color.White.copy(alpha = 0.2f) else Color.Transparent,
                                            RoundedCornerShape(8.dp)
                                        )
                                        .clickable { viewModel.selectedIconName = iconName },
                                    contentAlignment = Alignment.Center
                                ) {
                                    Icon(getIconByName(iconName), null, tint = if (isSelected) Color.White else Color.Gray, modifier = Modifier.size(24.dp))
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(8.dp))
                        Text(stringResource(R.string.select_color), color = Color.Gray, fontSize = 14.sp)
                        LazyRow(modifier = Modifier.padding(vertical = 8.dp)) {
                            items(availableColors) { colorHex ->
                                val isSelected = viewModel.selectedColorHex == colorHex
                                val color = Color(android.graphics.Color.parseColor(colorHex))
                                Box(
                                    modifier = Modifier
                                        .size(40.dp)
                                        .padding(4.dp)
                                        .background(color, CircleShape)
                                        .border(if (isSelected) 2.dp else 0.dp, Color.White, CircleShape)
                                        .clickable { viewModel.selectedColorHex = colorHex }
                                )
                            }
                        }
                    }
                },
                confirmButton = { TextButton(onClick = { viewModel.createFolder() }) { Text(stringResource(R.string.confirm), color = Color(0xFF66BB6A)) } },
                dismissButton = { TextButton(onClick = { viewModel.showDialog = false; viewModel.resetDialogState() }) { Text(stringResource(R.string.cancel), color = Color(0xFF66BB6A)) } },
                containerColor = Color(0xFF1C1C1C)
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun FolderHeaderItem(
    folder: FolderEntity,
    storeCount: Int,
    isExpanded: Boolean,
    isHovering: Boolean,
    dndTarget: DragAndDropTarget,
    onToggle: () -> Unit,
    onDelete: () -> Unit
) {
    val density = LocalDensity.current
    val anchorWidthPx = with(density) { 80.dp.toPx() }
    var offsetX by remember { mutableStateOf(0f) }
    val animatedOffset by animateFloatAsState(targetValue = offsetX)
    val rotationAngle by animateFloatAsState(targetValue = if (isExpanded) 0f else -90f)

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .draggable(
                state = rememberDraggableState { delta -> offsetX = (offsetX + delta).coerceIn(-anchorWidthPx, 0f) },
                orientation = Orientation.Horizontal,
                onDragStopped = { offsetX = if (offsetX < -anchorWidthPx / 2) -anchorWidthPx else 0f }
            )
    ) {
        Box(
            modifier = Modifier.fillMaxHeight().width(80.dp).align(Alignment.CenterEnd)
                .background(Color(0xFFFF5252), RoundedCornerShape(12.dp))
                .clickable { onDelete() },
            contentAlignment = Alignment.Center
        ) { Text(stringResource(R.string.delete), color = Color.White, fontWeight = FontWeight.Bold) }

        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .offset { IntOffset(animatedOffset.roundToInt(), 0) }
                .dragAndDropTarget(
                    shouldStartDragAndDrop = { it.toAndroidDragEvent().clipDescription?.hasMimeType(ClipDescription.MIMETYPE_TEXT_PLAIN) == true },
                    target = dndTarget
                )
                .clickable { onToggle() },
            color = if (isHovering) Color(0xFF384539) else Color(0xFF1C1C1C), // 改用較深的顏色與底色區隔
            shape = RoundedCornerShape(12.dp)
        ) {
            Row(modifier = Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = getIconByName(folder.iconName), 
                    contentDescription = null, 
                    tint = Color(android.graphics.Color.parseColor(folder.colorHex)), 
                    modifier = Modifier.size(24.dp)
                )
                Spacer(modifier = Modifier.width(12.dp))
                Text(text = folder.name, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(text = "$storeCount", color = Color.Gray, fontSize = 14.sp, modifier = Modifier.padding(end = 8.dp))
                Icon(Icons.Default.KeyboardArrowDown, null, tint = Color.Gray, modifier = Modifier.rotate(rotationAngle))
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun FavoriteStoreItem(
    storeName: String,
    pid: String,
    isHovering: Boolean,
    dndTarget: DragAndDropTarget?,
    onClick: () -> Unit
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp, horizontal = 8.dp)
            // 將點擊與長按拖曳整合，避免手勢衝突
            .dragAndDropSource(block = {
                detectTapGestures(
                    onTap = { onClick() },
                    onLongPress = {
                        startTransfer(
                            DragAndDropTransferData(
                                ClipData.newPlainText("pid", pid)
                            )
                        )
                    }
                )
            }),
        color = if (isHovering) Color(0xFF333333) else Color(0xFF252525),
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(0.5.dp, Color.White.copy(alpha = 0.2f))
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(text = storeName, color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Medium)
        }
    }
}
