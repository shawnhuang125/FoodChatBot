package com.example.ksuapp.Store_Data

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.*
import androidx.compose.foundation.shape.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil.compose.rememberAsyncImagePainter
import com.example.ksuapp.FavoritePage.FavoriteManager
import com.example.ksuapp.R
import kotlinx.coroutines.launch
import java.util.Calendar

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun StoreDetailed(
    store: StoreDetail,
    onClose: () -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val scrollState = rememberScrollState()
    
    val showStickyTitle by remember {
        derivedStateOf { scrollState.value > 100 }
    }

    val currentDayOfWeek = remember {
        val calendar = Calendar.getInstance()
        when (calendar.get(Calendar.DAY_OF_WEEK)) {
            Calendar.MONDAY -> "星期一"
            Calendar.TUESDAY -> "星期二"
            Calendar.WEDNESDAY -> "星期三"
            Calendar.THURSDAY -> "星期四"
            Calendar.FRIDAY -> "星期五"
            Calendar.SATURDAY -> "星期六"
            Calendar.SUNDAY -> "星期日"
            else -> ""
        }
    }

    var showPhotoSheet by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = false)
    val isFavorited by FavoriteManager.dao.isStoreFavorited(store.pid).collectAsState(initial = false)

    var showActionMenu by remember { mutableStateOf(false) }

    val surfaceColor = Color(0xFF1C1C1C)
    val cardColor = Color(0xFF252525)
    val primaryText = Color.White
    val secondaryText = Color(0xFFBDBDBD)
    val accentColor = Color(0xFF66BB6A)
    val brandBlue = Color(0xFF1D9BF0)

    Box(modifier = Modifier.fillMaxWidth().fillMaxHeight(0.9f).background(surfaceColor)) {
        
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scrollState)
                .padding(horizontal = 20.dp)
        ) {
            Spacer(modifier = Modifier.height(60.dp))

            Text(store.name, color = primaryText, fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(6.dp))
            RatingRow(rating = store.rating, tint = accentColor)
            
            if (store.distance.isNotBlank() && store.distance != "-") {
                Text(
                    text = stringResource(R.string.distance_label) + store.distance, 
                    color = secondaryText, 
                    fontSize = 13.sp, 
                    modifier = Modifier.padding(top = 4.dp)
                )
            }

            Spacer(modifier = Modifier.height(18.dp))
            StorePhotoRow(photos = store.photos, onMoreClick = { showPhotoSheet = true })
            
            Spacer(modifier = Modifier.height(24.dp))
            Text(stringResource(R.string.store_description), color = primaryText, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(12.dp))
            if (store.description.isNotBlank()) {
                Surface(color = Color.Transparent, shape = CircleShape, border = BorderStroke(1.dp, brandBlue.copy(0.5f))) {
                    Text(store.description, color = brandBlue, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
                }
            }

            Spacer(modifier = Modifier.height(20.dp))
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(cardColor)) {
                InfoRow(Icons.Default.Place, store.address, accentColor) {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(store.map_url.ifBlank { "geo:0,0?q=${store.address}" })))
                }
                InfoRow(Icons.Default.Phone, store.phone, accentColor) {
                    context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${store.phone}")))
                }
                
                if (store.website.isNotBlank() && 
                    store.website != "未知" && 
                    store.website != "無" && 
                    store.website.lowercase() != "nan") {
                    val displayWebsite = store.website
                        .replace("https://", "")
                        .replace("http://", "")
                        .split("/")
                        .firstOrNull() ?: ""

                    InfoRow(Icons.Default.Language, displayWebsite, accentColor) {
                        val webUri = if (store.website.startsWith("http")) store.website else "https://${store.website}"
                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(webUri)))
                    }
                }

                HorizontalDivider(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), color = Color.White.copy(0.06f))
                Text(
                    text = stringResource(R.string.opening_hours), 
                    color = secondaryText, 
                    fontSize = 13.sp, 
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                )
                Spacer(modifier = Modifier.height(8.dp))
                
                if (store.openingHours.isNotEmpty()) {
                    store.openingHours.forEach { (day, time) ->
                        val isToday = day.contains(currentDayOfWeek) && currentDayOfWeek.isNotEmpty()
                        Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp)) {
                            Text(
                                text = "$day $time",
                                color = if (isToday) accentColor else primaryText,
                                fontSize = 13.sp,
                                fontWeight = if (isToday) FontWeight.Bold else FontWeight.Normal,
                                lineHeight = 20.sp
                            )
                        }
                    }
                } else {
                    Text(
                        text = stringResource(R.string.no_opening_hours), 
                        color = primaryText, 
                        fontSize = 13.sp, 
                        modifier = Modifier.padding(horizontal = 16.dp)
                    )
                }
                Spacer(modifier = Modifier.height(16.dp))
            }

            if (store.facilityTags.isNotEmpty()) {
                SectionHeader(stringResource(R.string.service_tags))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    store.facilityTags.forEach { TagItem(it, brandBlue.copy(0.15f), brandBlue) }
                }
            }

            if (store.attributesTags.isNotEmpty()) {
                SectionHeader(stringResource(R.string.food_category_tags))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    store.attributesTags.forEach { TagItem(it, Color.White.copy(0.1f), Color.White.copy(0.7f)) }
                }
            }
            Spacer(modifier = Modifier.height(120.dp))
        }

        Surface(
            modifier = Modifier.fillMaxWidth().height(60.dp),
            color = if (showStickyTitle) surfaceColor.copy(alpha = 0.95f) else Color.Transparent,
            shadowElevation = if (showStickyTitle) 4.dp else 0.dp
        ) {
            Box(Modifier.fillMaxSize()) {
                Box(Modifier.padding(top = 10.dp).width(36.dp).height(4.dp).background(Color.White.copy(0.2f), CircleShape).align(Alignment.TopCenter))
                AnimatedVisibility(
                    visible = showStickyTitle,
                    enter = fadeIn() + slideInVertically { it / 2 },
                    exit = fadeOut() + slideOutVertically { it / 2 },
                    modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp)
                ) {
                    Text(text = store.name, color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(horizontal = 48.dp))
                }
            }
        }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(bottom = 32.dp, end = 24.dp)
                .navigationBarsPadding(),
            contentAlignment = Alignment.BottomEnd
        ) {
            Column(horizontalAlignment = Alignment.End) {
                AnimatedVisibility(
                    visible = showActionMenu,
                    enter = slideInVertically(initialOffsetY = { it / 2 }) + fadeIn(),
                    exit = slideOutVertically(targetOffsetY = { it / 2 }) + fadeOut()
                ) {
                    Card(
                        modifier = Modifier.padding(bottom = 16.dp).width(56.dp),
                        shape = CircleShape,
                        colors = CardDefaults.cardColors(containerColor = Color(0xFF333333)),
                        elevation = CardDefaults.cardElevation(8.dp)
                    ) {
                        Column(
                            modifier = Modifier.padding(vertical = 12.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(16.dp)
                        ) {
                            IconButton(onClick = {
                                showActionMenu = false
                                // 使用自定義 Scheme 格式，沒安裝 App 的使用者點了也沒反應
                                val shareLink = "ksuapp://share?pid=${store.pid}&name=${store.name}"
                                val sendIntent = Intent().apply {
                                    action = Intent.ACTION_SEND
                                    putExtra(Intent.EXTRA_TEXT, "我推薦 KSU APP 上的這間店：${store.name}\n$shareLink")
                                    type = "text/plain"
                                }
                                val shareIntent = Intent.createChooser(sendIntent, "分享 ${store.name}")
                                context.startActivity(shareIntent)
                            }) {
                                Icon(Icons.Default.Share, "Share", tint = Color.White, modifier = Modifier.size(24.dp))
                            }
                            IconButton(onClick = {
                                scope.launch {
                                    if (isFavorited) FavoriteManager.dao.deleteStoreByPid(store.pid)
                                    else FavoriteManager.addFavorite(store.pid, store.name)
                                }
                            }) {
                                Icon(
                                    imageVector = if (isFavorited) Icons.Filled.Bookmark else Icons.Filled.BookmarkBorder,
                                    contentDescription = "Favorite",
                                    tint = if (isFavorited) Color(0xFFFF5252) else Color.White,
                                    modifier = Modifier.size(24.dp)
                                )
                            }
                        }
                    }
                }

                FloatingActionButton(
                    onClick = { showActionMenu = !showActionMenu },
                    containerColor = if (showActionMenu) brandBlue else Color(0xFF333333),
                    contentColor = Color.White,
                    shape = CircleShape,
                    elevation = FloatingActionButtonDefaults.elevation(defaultElevation = 8.dp)
                ) {
                    Icon(
                        imageVector = if (showActionMenu) Icons.Default.Close else Icons.Default.MoreVert,
                        contentDescription = "More",
                        modifier = Modifier.size(28.dp)
                    )
                }
            }
        }
    }

    if (showPhotoSheet) {
        ModalBottomSheet(
            sheetState = sheetState,
            onDismissRequest = { showPhotoSheet = false },
            containerColor = surfaceColor,
            dragHandle = { BottomSheetDefaults.DragHandle(color = Color.White.copy(0.2f)) }
        ) {
            AllPhotoGrid(photos = store.photos)
        }
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(title, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 24.dp, bottom = 12.dp))
}

@Composable
private fun TagItem(text: String, bgColor: Color, textColor: Color) {
    Surface(color = bgColor, shape = CircleShape) {
        Text(text, color = textColor, fontSize = 12.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp))
    }
}

@Composable
private fun InfoRow(icon: ImageVector, value: String, valueColor: Color, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        color = Color.Transparent,
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.Top
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = Color(0xFF9E9E9E),
                modifier = Modifier.size(18.dp).offset(y = 1.dp)
            )
            Spacer(modifier = Modifier.width(16.dp))
            Text(
                text = value, 
                color = valueColor, 
                fontSize = 14.sp, 
                fontWeight = FontWeight.Medium, 
                lineHeight = 22.sp,
                modifier = Modifier.weight(1f)
            )
        }
    }
}

@Composable
fun RatingRow(rating: Double, tint: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        repeat(5) { i -> Icon(if (i < rating.toInt()) Icons.Filled.Star else Icons.Filled.StarBorder, null, tint = tint, modifier = Modifier.size(16.dp)) }
        Spacer(modifier = Modifier.width(6.dp))
        Text(String.format("%.1f", rating), color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun StorePhotoItem(imageUrl: String, modifier: Modifier = Modifier) {
    var showPreview by remember { mutableStateOf(false) }
    Box(modifier = modifier.aspectRatio(1f)) {
        Image(
            painter = rememberAsyncImagePainter(imageUrl),
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize().clip(RoundedCornerShape(8.dp)).pointerInput(Unit) { detectTapGestures(onTap = { showPreview = true }) }
        )
        if (showPreview) ImagePreviewDialog(imageUrl = imageUrl, onDismiss = { showPreview = false })
    }
}

@Composable
fun StorePhotoRow(photos: List<String>, onMoreClick: () -> Unit) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        val displayPhotos = photos.take(3)
        val hasMore = photos.size > 3
        displayPhotos.forEach { url -> StorePhotoItem(imageUrl = url, modifier = Modifier.weight(1f)) }
        if (hasMore) {
            Box(
                modifier = Modifier.weight(1f).aspectRatio(1f).clip(RoundedCornerShape(8.dp)).background(Color.White.copy(0.1f)).clickable { onMoreClick() },
                contentAlignment = Alignment.Center
            ) {
                Text(stringResource(R.string.more_photos), color = Color.White, fontSize = 11.sp, textAlign = TextAlign.Center)
            }
        } else {
            repeat(4 - displayPhotos.size) { Spacer(modifier = Modifier.weight(1f)) }
        }
    }
}

@Composable
fun AllPhotoGrid(photos: List<String>) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(3),
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(photos) { url -> StorePhotoItemGrid(imageUrl = url) }
    }
}

@Composable
fun StorePhotoItemGrid(imageUrl: String) {
    var showPreview by remember { mutableStateOf(false) }
    Box {
        Image(
            painter = rememberAsyncImagePainter(imageUrl),
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.aspectRatio(1f).clip(RoundedCornerShape(8.dp)).pointerInput(Unit) { detectTapGestures(onTap = { showPreview = true }) }
        )
        if (showPreview) ImagePreviewDialog(imageUrl = imageUrl, onDismiss = { showPreview = false })
    }
}

@Composable
fun ImagePreviewDialog(imageUrl: String, onDismiss: () -> Unit) {
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Box(
            modifier = Modifier.fillMaxSize().pointerInput(Unit) { detectTapGestures(onTap = { onDismiss() }) }.background(Color.Black.copy(alpha = 0.9f)),
            contentAlignment = Alignment.Center
        ) {
            Image(painter = rememberAsyncImagePainter(model = imageUrl), contentDescription = null, modifier = Modifier.fillMaxWidth(), contentScale = ContentScale.FillWidth)
        }
    }
}
