# app/utils/quality_checker.py

def analyze_search_results(all_results, plan, total_count, vector_search_info, rdb_info):
    """
    [綜合分析門面]
    合併狀態診斷與品質評價。
    注意：這裡傳入 all_results 以獲得最準確的全域診斷。
    """
    # 1. 取得搜尋狀態診斷 (移除重複的分頁資訊)
    # 這裡假設 check_search_status 內部僅回傳狀態字串 (如 "success", "no_match")
    search_status = check_search_status(all_results, plan, total_count=total_count)

    # 2. 取得品質標籤、降階旗標與 AI 指南
    quality_label, is_fallback, ai_hint = evaluate_search_quality(
        all_results,
        vector_search_info,
        rdb_info=rdb_info,
        plan=plan
    )

    return search_status, quality_label, is_fallback, ai_hint

def evaluate_search_quality(db_results, vector_search_info, rdb_info, plan):
    custom_status = vector_search_info.get("status")
    
    status = rdb_info.get("status")
    if status == "sql_no_data":
        return "no_data", True, "抱歉，目前搜尋範圍內沒有符合您『硬性要求』的店家。建議您可以換個位置或取消部分標籤再試試。"
    
    if custom_status == "no_data" or not db_results:
        return "no_data", True, "完全找不到符合條件的資料，請誠實告訴用戶並建議放寬篩選範圍。"

    if custom_status == "exact_one_match":
        return "success", False, "精確找到唯一匹配的店家，請以肯定的語氣推薦此店家。"

    is_fallback = False
    quality_label = "success"
    ai_hint = "搜尋成功，已找到多筆符合條件的店家。"

    if custom_status == "no_match":
        is_fallback = True
        quality_label = "partial_success"
        ai_hint = "無法找到與描述完全一致的店家，原本的嚴格條件查無結果，已自動為您放寬條件搜尋。"

    return quality_label, is_fallback, ai_hint


def check_search_status(all_results, plan, total_count=0):
    """
    技術診斷門面：檢查搜尋過程狀態、位置來源及 SQL 命中統計。
    已移除分頁資訊 (current_page, has_next 等)，改由 pagination 欄位統一處理。
    """
    has_results = len(all_results) > 0
    
    # 判斷搜尋行為標籤
    # skipped: 跳過向量 (純SQL); no_match: 完全沒資料; success: 正常完成
    if total_count == 0:
        status_label = "no_match"
    elif not plan.get("vector_needed"):
        status_label = "skipped"
    else:
        status_label = "success"

    # 初始化狀態包
    status_info = {
        "status": status_label,
        "location_info": {
            "type": "none",
            "message": "本次搜尋未涉及位置運算。",
            "coordinates": None
        },
        "total_count": total_count,          # 第一階段 SQL 基礎過濾的查詢店家數量
        "is_incomplete_search": False,       # 標記本次搜尋是否完整執行
        "no_results_found": not has_results,
        "suggestion": "",                    # 查無資料時的診斷建議
        "debug_details": None                # 供開發者除錯的詳細資訊
    }

    # --- 1. 處理位置資訊 (Location Diagnostics) ---
    if plan.get("distance_needed"):
        loc = plan.get("user_location")
        source = plan.get("location_source")
        
        if source == "default":
            status_info["location_info"] = {
                "type": "default_fallback",
                "message": "未偵測到位置，目前以系統預設點 (崑山科大) 計算距離。",
                "coordinates": loc
            }
        elif source == "user":
            status_info["location_info"] = {
                "type": "user_provided",
                "message": "已根據您提供的位置計算距離。",
                "coordinates": loc
            }

    # --- 2. 處理查無資料時的技術建議 (Error Diagnostics) ---
    if not has_results:
        active_params = plan.get("query_params", {})
        
        status_info["debug_details"] = {
            "applied_filters": active_params,
            "sql_where_clause": plan.get("generated_where_clause"),
            "vector_search_needed": plan.get("vector_needed")
        }

        # 針對不同失敗原因給予 AI 或前端建議
        if plan.get("vector_needed"):
            status_info["suggestion"] = "語意匹配失敗。建議放寬描述（如：減少特色標籤需求）。"
        elif active_params:
            # 檢查是否有設施標籤過濾 (數值 1 代表 True)
            has_facility = any(v == 1 for v in active_params.values() if isinstance(v, int))
            if has_facility:
                status_info["suggestion"] = "目前設施條件（如：冷氣、內用）組合過於嚴格，建議減少勾選項目。"
            else:
                status_info["suggestion"] = "目前關鍵字搜尋不到店家，請更換關鍵字。"
        else:
            status_info["suggestion"] = "SQL 基礎過濾查無資料，建議擴大搜尋範圍。"
            
    return status_info
