package com.example.ksuapp.Store_Data

import androidx.compose.runtime.mutableStateListOf

object StoreDataManager {
    private val storeDetailList = mutableStateListOf<StoreDetailData>()

    @Volatile
    private var isSummaryCollecting = false

    fun upsertDetail(store: StoreDetailData) {
        val index = storeDetailList.indexOfFirst { it.id == store.id }
        if (index >= 0) {
            storeDetailList[index] = store
        } else {
            storeDetailList.add(store)
        }
    }

    fun findDetailById(pid: String): StoreDetailData? {
        return storeDetailList.find { it.id.toString() == pid }
    }

    fun findDetailBySummary(summaryText: String): StoreDetailData? {
        val normalizedSummary = normalize(summaryText)
        return storeDetailList.firstOrNull { store ->
            val normalizedName = normalize(store.name)
            normalizedSummary.startsWith(normalizedName)
        }
    }

    fun onSummaryTextReceived(text: String) {
        when {
            text.contains("<start>") -> isSummaryCollecting = true
            text.contains("<end>") -> isSummaryCollecting = false
        }
    }

    fun isSummaryCollecting(): Boolean = isSummaryCollecting

    fun resetSummary() {
        isSummaryCollecting = false
    }

    fun clearDetails() {
        storeDetailList.clear()
    }

    private fun normalize(text: String): String {
        return text.replace(" ", "").replace("　", "").replace("\n", "").trim()
    }
}
