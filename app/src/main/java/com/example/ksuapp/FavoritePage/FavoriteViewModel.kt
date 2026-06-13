package com.example.ksuapp.FavoritePage

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.ksuapp.AppLog
import com.example.ksuapp.Network.HttpClient
import com.example.ksuapp.Network.SocketClient
import com.example.ksuapp.Store_Data.StoreDataManager
import com.example.ksuapp.Store_Data.StoreDetail
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class FavoriteViewModel : ViewModel() {

    private val MODULE = "FavoritePage"

    val folders: StateFlow<List<FolderWithStores>> = FavoriteManager.dao
        .getAllFoldersWithStores()
        .stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    var showDetail by mutableStateOf(false)
    var selectedStore by mutableStateOf<StoreDetail?>(null)
    var showDialog by mutableStateOf(false)
    
    // 🔍 搜尋相關狀態
    var isSearchMode by mutableStateOf(false)
    var searchQuery by mutableStateOf("")

    val searchResults = derivedStateOf {
        if (searchQuery.isBlank()) return@derivedStateOf emptyList<FavoriteStoreEntity>()
        folders.value.flatMap { it.stores }.filter { 
            it.name.contains(searchQuery, ignoreCase = true) 
        }
    }

    // 資料夾建立狀態
    var newFolderName by mutableStateOf("")
    var selectedIconName by mutableStateOf("Folder")
    var selectedColorHex by mutableStateOf("#66BB6A")
    
    val expandedStates = mutableStateMapOf<String, Boolean>()
    val hoveringFolders = mutableStateMapOf<Int, Boolean>()

    fun toggleFolder(folderName: String) {
        expandedStates[folderName] = !(expandedStates[folderName] ?: true)
    }

    fun setFolderHovering(folderId: Int, isHovering: Boolean) {
        hoveringFolders[folderId] = isHovering
    }

    fun createFolder() {
        if (newFolderName.isNotBlank()) {
            val name = newFolderName
            val icon = selectedIconName
            val color = selectedColorHex
            viewModelScope.launch {
                FavoriteManager.createFolder(name, icon, color)
                resetDialogState()
                showDialog = false
            }
        }
    }

    fun resetDialogState() {
        newFolderName = ""
        selectedIconName = "Folder"
        selectedColorHex = "#66BB6A"
    }

    fun removeFolder(folder: FolderEntity) {
        viewModelScope.launch {
            FavoriteManager.dao.deleteFolder(folder)
            AppLog.i("資料庫：刪除分類 (${folder.name})", MODULE)
        }
    }

    fun moveStore(pid: String, toFolderId: Int) {
        viewModelScope.launch {
            FavoriteManager.dao.moveStore(pid, toFolderId)
            AppLog.i("資料庫：移動店家($pid) ➡️ 目標ID($toFolderId)", MODULE)
        }
    }

    fun loadStoreDetail(pid: String, name: String) {
        val sid = SocketClient.getSid() ?: ""
        val url = "http://192.168.1.112:5003/get_place_info/$pid?sid=$sid&user_lat=0.0000000&user_lng=0.0000000"
        HttpClient.send(url)
        
        viewModelScope.launch {
            for (i in 1..50) {
                val detail = StoreDataManager.findDetailById(pid)
                if (detail != null) {
                    selectedStore = StoreDetail(
                        pid = detail.id.toString(),
                        name = detail.name,
                        rating = detail.rating,
                        photos = detail.photos,
                        summary = detail.name,
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
                    showDetail = true
                    break
                }
                delay(100)
            }
        }
    }
}
