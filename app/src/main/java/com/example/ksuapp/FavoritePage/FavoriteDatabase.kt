package com.example.ksuapp.FavoritePage

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(entities = [FolderEntity::class, FavoriteStoreEntity::class], version = 2, exportSchema = false)
abstract class FavoriteDatabase : RoomDatabase() {
    
    abstract fun favoriteDao(): FavoriteDao

    companion object {
        @Volatile
        private var INSTANCE: FavoriteDatabase? = null

        fun getDatabase(context: Context): FavoriteDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    FavoriteDatabase::class.java,
                    "ksu_favorite_database"
                )
                .fallbackToDestructiveMigration() // 簡易版本升級策略
                .build()
                INSTANCE = instance
                instance
            }
        }
    }
}
