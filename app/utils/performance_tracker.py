# ./app/utils/performance_tracker.py
import csv
import os
import logging
from datetime import datetime
from app.config import Config

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