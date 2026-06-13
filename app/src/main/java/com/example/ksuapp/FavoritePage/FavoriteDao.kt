package com.example.ksuapp.FavoritePage

import androidx.room.*
import kotlinx.coroutines.flow.Flow

@Dao
interface FavoriteDao {

    // 取得所有資料夾及其內部的店家
    @Transaction
    @Query("SELECT * FROM folders")
    fun getAllFoldersWithStores(): Flow<List<FolderWithStores>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertFolder(folder: FolderEntity): Long

    @Delete
    suspend fun deleteFolder(folder: FolderEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertStore(store: FavoriteStoreEntity)

    @Delete
    suspend fun deleteStore(store: FavoriteStoreEntity)

    @Query("DELETE FROM favorite_stores WHERE pid = :pid")
    suspend fun deleteStoreByPid(pid: String)
    
    @Query("UPDATE favorite_stores SET folderId = :newFolderId WHERE pid = :pid")
    suspend fun moveStore(pid: String, newFolderId: Int)

    @Query("SELECT * FROM folders WHERE name = :name LIMIT 1")
    suspend fun getFolderByName(name: String): FolderEntity?

    @Query("SELECT EXISTS(SELECT 1 FROM favorite_stores WHERE pid = :pid)")
    fun isStoreFavorited(pid: String): Flow<Boolean>
}

// 輔助資料類別：用來承接關聯查詢結果
data class FolderWithStores(
    @Embedded val folder: FolderEntity,
    @Relation(
        parentColumn = "id",
        entityColumn = "folderId"
    )
    val stores: List<FavoriteStoreEntity>
)
