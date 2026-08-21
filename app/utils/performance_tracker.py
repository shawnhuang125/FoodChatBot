# ./app/utils/performance_tracker.py
import csv
import os
import re
import logging
from datetime import datetime
from app.config import Config
from typing import List, Dict, Any, Optional
from app.utils.app_logger import logger


def log_performance_to_csv(metrics: dict):
    """
    記錄 Route 層的整體搜尋效能。
    儲存於: Config.PERFORMANCE_LOG_PATH
    """
    # 檢查檔案是否存在
    file_path = Config.PERFORMANCE_LOG_PATH
    file_exists = os.path.isfile(file_path)
    
    header = [
        "搜尋架構", "目前店家總數", "搜尋意圖內容", "命中筆數", 
        "SQL_Service耗時", "SQL轉Vector過渡耗時", "Qdrant查詢耗時", 
        "指標排序耗時", "總耗時(Route層)", "紀錄時間"
    ]
    
    try:
        with open(file_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            
            if not file_exists:
                writer.writeheader()
            
            writer.writerow({
                "搜尋架構": Config.SEARCH_ARCHITECTURE,
                "目前店家總數": Config.CURRENT_PLACE_COUNT,
                "搜尋意圖內容": metrics.get("intent_content", "N/A"),
                "命中筆數": metrics.get("hit_count", 0),
                "SQL_Service耗時": metrics.get("sql_service"),
                "SQL轉Vector過渡耗時": metrics.get("transition"),
                "Qdrant查詢耗時": metrics.get("qdrant"),
                "指標排序耗時": metrics.get("ranking"),
                "總耗時(Route層)": metrics.get("total"),
                "紀錄時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception as e:
        logging.error(f"寫入整體效能 CSV 失敗: {e}")


def log_function_timing(func_name: str, s_id: str, duration: float):
    """
    記錄 Service 層個別函式的執行耗時。
    儲存於: Config.FUNC_TIMING_LOG_PATH (建議在 Config 新增此設定)
    """
    # 如果 Config 沒定義新路徑，我們手動在原路徑旁加個字尾
    file_path = getattr(Config, 'FUNC_TIMING_LOG_PATH', Config.PERFORMANCE_LOG_PATH.replace(".csv", "_detail.csv"))
    
    file_exists = os.path.isfile(file_path)
    header = ["函式名稱", "Session_ID", "耗時(秒)", "紀錄時間"]

    try:
        with open(file_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            if not file_exists:
                writer.writerow(header)
                
            writer.writerow([
                func_name, 
                s_id or "N/A", 
                round(duration, 4), 
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ])
    except Exception as e:
        logging.error(f"寫入函式細節耗時失敗 ({func_name}): {e}")

def log_experiment_intent_to_csv(plan: dict, stores: list):
    """
    【實驗專用 - 獨立存檔版】
    每次搜尋都會在 experiment_logs 目錄下，以 Session_ID + 時間戳記建立一檔獨立的 CSV。
    記錄該次使用者輸入的向量關鍵字、實際執行的檢索語句，與產出的所有店家的菜系/食物種類特徵。
    """
    try:
        # 1. 建立資料夾結構
        base_log_dir = os.path.dirname(getattr(Config, 'PERFORMANCE_LOG_PATH', 'logs/performance.csv'))
        exp_dir = os.path.join(base_log_dir, "experiment_logs")
        os.makedirs(exp_dir, exist_ok=True)

        # 2. 取得 Session ID 與時間戳記
        s_id = str(plan.get("s_id", "unknown_sid")).strip()
        safe_sid = re.sub(r'[^a-zA-Z0-9_-]', '_', s_id)
        timestamp_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"intent_exp_{safe_sid}_{timestamp_filename}.csv"
        file_path = os.path.join(exp_dir, file_name)

        # 🟢 3. 修改 CSV 表頭：在「使用者意圖」與「店家ID」中間插入「實際檢索語句(vector_queries)」
        header = [
            "Session_ID",
            "搜尋時間",
            "使用者輸入_菜系意圖(cuisine)",
            "使用者輸入_食物種類意圖(food_type)",
            "實際檢索語句(vector_queries)",          # 👈 新增這個關鍵欄位
            "店家ID",
            "店家名稱",
            "店家向量指標_菜系(cuisine)",
            "店家向量指標_食物種類(food_type)"
        ]

        # 4. 準備所有要轉成字串的意圖與查詢內容
        keywords = plan.get("vector_keywords", {})
        
        def _to_str(val):
            if isinstance(val, list):
                return " | ".join([str(i).strip() for i in val if str(i).strip()])
            return str(val).strip() if val else "無"

        user_cuisine_str = _to_str(keywords.get("cuisine"))
        user_food_type_str = _to_str(keywords.get("food_type"))
        
        # 🟢 讀取剛剛從 vector_service 存回 plan 的「實際檢索字串」
        executed_queries = plan.get("executed_vector_queries", ["未執行向量檢索"])
        vector_query_str = _to_str(executed_queries)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 5. 建立檔案並寫入內容
        with open(file_path, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(header)

            # 🟢 情況 A：完全沒搜到店家 (保底寫入一列)
            if not stores:
                writer.writerow([
                    s_id,
                    now_str,
                    user_cuisine_str,
                    user_food_type_str,
                    vector_query_str,                # 👈 寫入實際檢索字串
                    "N/A",
                    "查無符合條件店家",
                    "無",
                    "無"
                ])
            # 🟢 情況 B：有搜到店家 (逐列寫入)
            else:
                for store in stores:
                    store_cuisine = str(store.get("cuisine", "無")) or "無"
                    store_food_type = str(store.get("food_type", "無")) or "無"
                    
                    writer.writerow([
                        s_id,
                        now_str,
                        user_cuisine_str,
                        user_food_type_str,
                        vector_query_str,            # 👈 寫入實際檢索字串
                        store.get("id", "N/A"),
                        store.get("restaurant_name", "未命名"),
                        store_cuisine,
                        store_food_type
                    ])
                
        logging.info(f"[實驗數據追蹤] 當次意圖與店家指標已獨立儲存至: {file_path}")

    except Exception as e:
        logging.error(f"寫入獨立實驗意圖 CSV 失敗: {e}", exc_info=True)





EXPERIMENT_LOG_DIR = "experiment_logs"

def log_semantic_scores_to_csv(
    s_id: str,
    raw_scores_data: List[Dict[str, Any]],
    logic_threshold: float,
    filepath: Optional[str] = None 
):
    """
    論文實驗專用：每一次搜尋獨立存成一個全新的 CSV 檔案
    檔名範例：experiment_logs/scores_abc123_20260811_172530_th0.6.csv
    """
    try:
        os.makedirs(EXPERIMENT_LOG_DIR, exist_ok=True)
        
        if not filepath:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"scores_{s_id}_{timestamp}_th{logic_threshold}.csv"
            filepath = os.path.join(EXPERIMENT_LOG_DIR, filename)

        fieldnames = [
            "s_id",
            "restaurant_id",
            "field_key",         # 選擇的欄位 (例: cuisine, service_tags)
            "target_keyword",    # 搜尋關鍵字 (例: 火鍋, 包廂)
            "store_raw_array",   # 店家該欄位的原始內容
            "similarity_score",  # 餘弦相似度分數
            "logic_threshold",   # 實驗門檻
            "passed_gate"        # 是否通過門檻 (True / False)
        ]

        with open(filepath, mode="w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            for record in raw_scores_data:
                r_id = record["restaurant_id"]
                passed = record["passed_gate"]

                for feat in record["features"]:
                    writer.writerow({
                        "s_id": s_id,
                        "restaurant_id": r_id,
                        "field_key": feat["field_key"],
                        "target_keyword": feat["target_keyword"],
                        "store_raw_array": feat["store_raw_array"],
                        "similarity_score": round(feat["score"], 4),
                        "logic_threshold": logic_threshold,
                        "passed_gate": passed
                    })

        logger.info(f"📊 [Experiment Logger][SID: {s_id}] 已成功獨立存檔至: {filepath}")

    except Exception as e:
        logger.error(f"❌ [Experiment Logger Error] 獨立存檔 CSV 失敗: {e}", exc_info=True)