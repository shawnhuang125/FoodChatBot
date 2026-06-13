package com.example.ksuapp.FavoritePage

import android.content.Context
import com.example.ksuapp.AppLog

object FavoriteManager {

    private var database: FavoriteDatabase? = null
    val dao get() = database?.favoriteDao() ?: throw IllegalStateException("FavoriteManager 未初始化")

    fun init(context: Context) {
        if (database == null) {
            database = FavoriteDatabase.getDatabase(context)
        }
    }

    suspend fun addFavorite(pid: String, name: String) {
        val allFolders = dao.getFolderByName("未分類")
        val targetFolderId = allFolders?.id ?: dao.insertFolder(FolderEntity(name = "未分類")).toInt()
        
        dao.insertStore(FavoriteStoreEntity(pid = pid, name = name, folderId = targetFolderId))
        AppLog.i("資料庫：新增收藏店家 ($name)", "FavoritePage")
    }

    suspend fun createFolder(name: String, iconName: String, colorHex: String) {
        dao.insertFolder(FolderEntity(name = name, iconName = iconName, colorHex = colorHex))
        AppLog.i("資料庫：建立資料夾 ($name)", "FavoritePage")
    }
}
