package com.example.ksuapp.Store_Data

data class StorePidData(
    val pids: List<String>
)

data class StoreSummaryCardModel(
    val pid: String,
    val name: String,
    val summary: String? = null
)

data class StoreDetailData(
    val id: Int,
    val name: String,
    val address: String,
    val phone: String,
    val website: String,
    val opening_hours: Map<String, String>,
    val rating: Double,
    val distance: String,
    val facility_tags: List<String>,
    val attributes_tags: List<String>,
    val merchant_categories: String,
    val map_url: String,
    val photos: List<String>
)

data class StoreDetail(
    val pid: String,
    val name: String,
    val rating: Double,
    val photos: List<String>,
    val summary: String?,
    val description: String,
    val address: String,
    val phone: String,
    val openingHours: Map<String, String>,
    val facilityTags: List<String>,
    val distance: String,
    val website: String,
    val map_url: String,
    val attributesTags: List<String>
)
