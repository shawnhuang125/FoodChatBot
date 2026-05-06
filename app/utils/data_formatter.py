# app/utils/data_formatter.py
import json
from app.config import Config 
from typing import Optional


def format_facility_tags(results):
    for row in results:
        raw_tags = row.get("facility_tags")
        
        # 1. 如果已經是 List (這是你資料庫目前的真實狀況)
        if isinstance(raw_tags, list):
            # 直接保留，不需處理，或者做點過濾
            row["facility_tags"] = raw_tags
            
        # 2. 如果是 Dict (相容舊邏輯或未來可能的變動)
        elif isinstance(raw_tags, dict):
            processed_list = [k for k, v in raw_tags.items() if v is True]
            row["facility_tags"] = processed_list
            
        # 3. 其他情況 (包含 None)
        else:
            row["facility_tags"] = []
            
    return results

def enrich_results_with_photos(results, plan):
    """
    參數:
      results: SQL 查回來的 List[Dict] 結果
      plan: analyze_intent 產出的計畫書
    """
    # 只有當計畫書說「我需要照片」時才執行
    if not plan.get("photos_needed"):
        return results

    # 建議：未來可以改從 Config 讀取，例如 Config.IMAGE_BASE_URL
    base_url = Config.IMAGES_URL

    for row in results:
        store_id = str(row['id']).zfill(3)
        row['photos'] = [] 
        
        # 根據規則：店家ID + 01~10.jpg
        for i in range(1, 11):
            # 檔名規則：[3位數店家ID][2位數流水號].jpg
            # 例如：00501.jpg, 09910.jpg
            photo_name = f"{store_id}{str(i).zfill(2)}.jpg"
            full_url = base_url + photo_name
            row['photos'].append(full_url)
            
    return results


# 若['opening_hours', 'facility_tags']有反斜線就把反斜線拿掉,否則不做任何動作就回傳
def parse_json_fields(results, fields_to_parse=None):
    if fields_to_parse is None:
        fields_to_parse = ['opening_hours', 'facility_tags']

    for row in results:
        for field in fields_to_parse:
            if field in row and isinstance(row[field], str):
                val = row[field]
                # 移除可能影響解析的反斜線與首尾引號
                cleaned_val = val.replace('\\', '')
                if cleaned_val.startswith('"') and cleaned_val.endswith('"'):
                    cleaned_val = cleaned_val[1:-1]
                
                try:
                    # 關鍵：將字串轉為 dict
                    row[field] = json.loads(cleaned_val)
                except Exception:
                    # 解析失敗時，給予 facility_tags 一個空字典以供後續函式處理
                    row[field] = {} if field == 'facility_tags' else cleaned_val
    return results

# 依照plan裡面去處理距離顯示與補上照片與格式化設施標籤 (只有 SQL 有選該欄位時才執行)
def format_response_data(results, plan):
    """
    根據 HybridSQLBuilder 產出的 plan，動態決定要執行的後處理步驟。
    """
    # 取得計畫中標記的需求
    needed_fields = plan.get("select_fields", [])
    photos_needed = plan.get("photos_needed", False)
    distance_needed = plan.get("distance_needed", False)
    
    # 解析 JSON 欄位 (根據 SQL 欄位別名判斷)
    # 檢查 plan 中的 select_fields 字串清單，判斷是否有對應欄位
    parse_targets = []
    if any("AS opening_hours" in f for f in needed_fields):
        parse_targets.append("opening_hours")
    if any("AS facility_tags" in f for f in needed_fields):
        parse_targets.append("facility_tags")
        
    if parse_targets:
        results = parse_json_fields(results, fields_to_parse=parse_targets)
    
    # 格式化設施標籤 (只有 SQL 有選該欄位時才執行)
    if any("AS facility_tags" in f for f in needed_fields):
        results = format_facility_tags(results)
    
    # 處理距離顯示
    if distance_needed:
        results = format_distance_display(results)
        
    # 補上照片 (依據 plan 決定)
    if photos_needed:
        
        results = enrich_results_with_photos(results, plan)
        
    return results

# 距離資料的格式化
def format_distance_display(results):
    """
    距離資料的格式化
    """
    for row in results:
        if 'distance' in row and row['distance'] is not None:
            try:
                dist_m = float(row['distance'])
                
                if dist_m >= 1000:
                    # 例如 2500 公尺 -> "2.500 km"
                    row['distance'] = f"{dist_m / 1000:.2f} km" # 建議改兩位小數比較清爽
                else:
                    # 例如 300 公尺 -> "300 m"
                    row['distance'] = f"{int(dist_m)} m"
                    
            except (ValueError, TypeError):
                pass
    return results

