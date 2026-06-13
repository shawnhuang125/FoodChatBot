package com.example.ksuapp.FavoritePage

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "folders")
data class FolderEntity(
    @PrimaryKey(autoGenerate = true) val id: Int = 0,
    val name: String,
    val iconName: String = "Folder",
    val colorHex: String = "#66BB6A"
)

@Entity(
    tableName = "favorite_stores",
    foreignKeys = [
        ForeignKey(
            entity = FolderEntity::class,
            parentColumns = ["id"],
            childColumns = ["folderId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index(value = ["folderId"])]
)
data class FavoriteStoreEntity(
    @PrimaryKey val pid: String,
    val name: String,
    val folderId: Int
)
