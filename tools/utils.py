import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from dataset_manifest import TIME_SLOTS
from dataset_manifest import VOCAB

# 載入 .env 環境變數以讀取系統配置
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

# =====================================================================
# 1. 環境變數設定 (絕對禁止硬編碼)
# =====================================================================
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Taipei")
DEFAULT_SEARCH_DISTANCE = int(os.getenv("DEFAULT_SEARCH_DISTANCE", 1000))
PRIMARY_CONDITION_WEIGHT = float(os.getenv("PRIMARY_CONDITION_WEIGHT", 1.0))
WEIGHT_DECAY_RATE = float(os.getenv("WEIGHT_DECAY_RATE", 0.2))


# =====================================================================
# 2. 輔助邏輯：約束強度與權重計算
# =====================================================================
def _calculate_intensity_and_weight(user_input, index=0):
    """
    輔助函式：根據使用者輸入的語氣詞彙與條件順序，計算約束強度與權重。
    
    參數:
        user_input (str): 使用者的口語詞彙。
        index (int): 此條件在多重條件中的順序索引，用於權重遞減計算。
        
    回傳:
        tuple: (constraint_level, weight)
    """
    constraint_level = "MUST"
    # 1. 計算基礎權重 (Base Weight)
    base_weight = PRIMARY_CONDITION_WEIGHT - (index * WEIGHT_DECAY_RATE)
    final_weight = base_weight
    
    # 2. 實施強度修正 (Intensity Offset)
    if any(kw in user_input for kw in ["一定要", "絕對要", "必須", "規定要", "要在", "絕對", "指定"]):
        constraint_level = "MUST"
        final_weight += 0.1
    elif any(kw in user_input for kw in ["希望", "希望能", "大概", "左右", "順便", "隨便", "看看", "最好是", "可以的話", "想找", "有沒有"]):
        constraint_level = "SHOULD"
        final_weight -= 0.1
        
    # 3. 範圍鎖定與精度控制 (Clamping & Rounding)
    final_weight = min(1.0, max(0.1, final_weight))
        
    return constraint_level, round(final_weight, 2)


# =====================================================================
# 3. 核心工具：時間、地址、評分轉換函式
# =====================================================================
def parse_time_logic(base_date_str, user_time_input, index=0):
    """
    將使用者的口語時間詞彙轉換為系統 Logic Tree 2.0 規格的條件字典。
    
    支援精準時間點 (如：8點半、8:30) 的正則擷取與相對日期偏移，
    並支援預定義時段範圍 (如：宵夜)。

    參數:
        base_date_str (str): 基準時間字串，格式應為 "YYYY-MM-DD HH:mm:ss"。
        user_time_input (str): 使用者的口語時間詞彙 (如：「明晚」、「宵夜」、「今晚 8 點」)。
        index (int): 條件順序，預設為 0。
    """
    try:
        base_dt = datetime.strptime(base_date_str, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        base_dt = datetime.now()

    constraint_level, weight = _calculate_intensity_and_weight(user_time_input, index)

    # 1. 動態相對時間優先權 (即刻匹配，禁止 Fallback)
    if any(kw in user_time_input for kw in ["現在", "目前", "即刻"]):
        return {
            "field": "time",
            "value": [base_dt.strftime("%Y-%m-%d %H:%M:%S")],
            "cmp": "open_at",
            "constraint_level": constraint_level,
            "weight": weight
        }
    if any(kw in user_time_input for kw in ["待會", "等一下", "稍後"]):
        target_dt = base_dt + timedelta(hours=1)
        return {
            "field": "time",
            "value": [target_dt.strftime("%Y-%m-%d %H:%M:%S")],
            "cmp": "open_at",
            "constraint_level": constraint_level,
            "weight": weight
        }

    # 2. 動態相對時間偏移解析 (如：一小時後、半小時內、10分鐘內)
    # 容錯處理：加入 (?:個)? 以支援「一個小時」與「一小時」的口語差異
    offset_match = re.search(r'(\d+|半|一|兩|1|2)\s*(?:個)?\s*(小時|鐘頭|分鐘|分)\s*(後|內|左右)', user_time_input)
    if offset_match:
        num_str = offset_match.group(1)
        unit_str = offset_match.group(2)
        suffix = offset_match.group(3)
        
        if num_str == '半':
            total_minutes = 30
        else:
            if num_str.isdigit():
                val = int(num_str)
            else:
                num_map = {'一': 1, '兩': 2, '1': 1, '2': 2}
                val = num_map.get(num_str, 1)
                
            if unit_str in ['小時', '鐘頭']:
                total_minutes = val * 60
            else:
                total_minutes = val
                
        delta = timedelta(minutes=total_minutes)
            
        target_dt = base_dt + delta
        
        if suffix == '內':
            return {
                "field": "time",
                "value": [base_dt.strftime("%Y-%m-%d %H:%M:%S"), target_dt.strftime("%Y-%m-%d %H:%M:%S")],
                "cmp": "between",
                "constraint_level": constraint_level,
                "weight": weight
            }
        else:
            return {
                "field": "time",
                "value": [target_dt.strftime("%Y-%m-%d %H:%M:%S")],
                "cmp": "open_at",
                "constraint_level": constraint_level,
                "weight": weight
            }

    target_dt = base_dt
    is_weekend = False

    # 3. 日期偏移解析 (擴充星期幾與週末處理)
    if any(kw in user_time_input for kw in ["明天", "明晚"]):
        target_dt += timedelta(days=1)
    elif "後天" in user_time_input:
        target_dt += timedelta(days=2)
    elif "週末" in user_time_input:
        # 智慧跳轉：計算距離下一個週六的天數
        days_ahead = 5 - base_dt.weekday() # 星期六的 index 為 5
        if days_ahead <= 0:
            days_ahead += 7
        target_dt += timedelta(days=days_ahead)
        is_weekend = True
    else:
        # 星期映射邏輯：使用正則偵測「星期X」、「週X」或「禮拜X」
        weekday_match = re.search(r'(?:星期|週|禮拜)([一二三四五六日天])', user_time_input)
        if weekday_match:
            weekday_str = weekday_match.group(1)
            weekday_map = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
            target_weekday = weekday_map.get(weekday_str, 0)
            
            # 取得 base_dt 的當前星期，計算天數差距 (days_ahead)
            days_ahead = target_weekday - base_dt.weekday()
            
            # 若 days_ahead <= 0，代表該天已過或就是今天，自動加上 7 天尋找下週該日
            if days_ahead <= 0:
                days_ahead += 7
                
            target_dt += timedelta(days=days_ahead)
        # 「今天」、「今晚」或未指定則維持基準日期

    # ==========================================
    # 3. 第一順位 (精確時點)：精確數字優先解析
    # ==========================================
    # [開發規範註解]：為何「數字正則」必須放在「口語映射」之前執行？
    # 因為當使用者輸入如「晚上八點」時，同時包含了廣泛時段「晚上」與精確數字「八點」。
    # 若先比對口語映射，會被提前攔截為「晚上」的廣泛區間 (Between mode) 而造成誤判。
    # 優先執行數字正則掃描，能精準鎖定時間並返回 open_at 模式，區分出「晚上」與「晚上八點」的差異。
    
    time_resolved = False
    
    # 預處理：將中文時間數字轉換為阿拉伯數字 (例如：八點 -> 8點)
    ch_nums = {'十二': '12', '十一': '11', '十': '10', '九': '9', '八': '8', '七': '7', '六': '6', '五': '5', '四': '4', '三': '3', '兩': '2', '二': '2', '一': '1'}
    processed_time_input = user_time_input
    for ch, num in ch_nums.items():
        processed_time_input = re.sub(f'{ch}(?=[點時:])', num, processed_time_input)

    time_match = re.search(r'(\d{1,2})(?:[:點時])(\d{1,2})?(半)?', processed_time_input)
    if time_match:
        hour = int(time_match.group(1))
        minute = 0
        if time_match.group(2):
            minute = int(time_match.group(2))
        elif time_match.group(3) == '半':
            minute = 30
        
        # 語意校正：結合語句中的「下午/晚上」進行 24 小時制轉換
        if any(kw in user_time_input for kw in ["下午", "傍晚", "晚上", "晚", "深夜", "半夜"]):
            if hour < 12: hour += 12
        elif any(kw in user_time_input for kw in ["凌晨", "清晨", "半夜", "深夜"]):
            if hour == 12: hour = 0
            
        target_dt = target_dt.replace(hour=hour, minute=minute, second=0)
        time_resolved = True
    else:
        # 寬鬆數字比對 (例如「晚上8」但沒加「點」)
        loose_match = re.search(r'(\d{1,2})', processed_time_input)
        if loose_match:
            hour = int(loose_match.group(1))
            if hour <= 24:
                # 語意校正：結合語句中的「下午/晚上」進行 24 小時制轉換
                if any(kw in user_time_input for kw in ["下午", "傍晚", "晚上", "晚", "深夜", "半夜"]) and hour < 12:
                    hour += 12
                elif any(kw in user_time_input for kw in ["凌晨", "清晨", "半夜", "深夜"]) and hour == 12:
                    hour = 0
                target_dt = target_dt.replace(hour=hour if hour < 24 else 0, minute=0, second=0)
                time_resolved = True
            
    # 4. 輸出模式：只要有數字，cmp 必須設為 open_at
    if time_resolved:
        # 智慧日期判定連動：若時點已過且沒說「今天」，則自動 +1天
        if target_dt < base_dt and not any(kw in user_time_input for kw in ["今天", "今日", "今晚"]):
            target_dt += timedelta(days=1)
            
        return {
            "field": "time",
            "value": [target_dt.strftime("%Y-%m-%d %H:%M:%S")],
            "cmp": "open_at",
            "constraint_level": constraint_level,
            "weight": weight
        }

    # ==========================================
    # 5. 第二順位 (口語區間)：完全沒有數字時，比對 keyword_map (Between Mode)
    # ==========================================
    broad_time_ranges = {
        "凌晨": ("00:00:00", "05:59:59"),
        "清晨": ("05:00:00", "07:59:59"),
        "早上": ("06:00:00", "11:59:59"),
        "上午": ("08:00:00", "11:59:59"),
        "中午": ("11:00:00", "13:59:59"),
        "下午茶": ("14:00:00", "16:59:59"),
        "下午": ("13:00:00", "17:59:59"),
        "傍晚": ("17:00:00", "19:59:59"),
        "晚餐": ("17:30:00", "21:30:59"),
        "晚上": ("18:00:00", "23:59:59"),
        "半夜": ("23:00:00", "03:59:59"),
        "深夜": ("23:00:00", "03:59:59"),
        "打烊前": ("22:00:00", "23:59:59")
    }
    
    # 整合 dataset_manifest.py 的 TIME_SLOTS
    for kw, (st, et) in TIME_SLOTS.items():
        broad_time_ranges[kw] = (st, et)

    for kw, (st, et) in broad_time_ranges.items():
        if kw in user_time_input:
            st_hour, st_min, st_sec = map(int, st.split(':'))
            et_hour, et_min, et_sec = map(int, et.split(':'))
            
            start_dt = target_dt.replace(hour=st_hour, minute=st_min, second=st_sec)
            end_dt = target_dt.replace(hour=et_hour, minute=et_min, second=et_sec)
            
            # 若起訖跨日 (例如 22:00 到 03:00)
            if end_dt < start_dt:
                end_dt += timedelta(days=1)
                
            # 智慧日期判定：若解析出的區間已過，自動偏移到「隔天」的對應區間
            if end_dt < base_dt and not any(k in user_time_input for k in ["今天", "今日", "今晚"]):
                start_dt += timedelta(days=1)
                end_dt += timedelta(days=1)
                
            return {
                "field": "time",
                "value": [start_dt.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S")],
                "cmp": "between",
                "constraint_level": constraint_level,
                "weight": weight
            }

    # 6. 如果只偵測到「週末」
    if is_weekend:
        start_dt = target_dt.replace(hour=0, minute=0, second=0) # 週六 00:00:00
        end_dt = (target_dt + timedelta(days=1)).replace(hour=23, minute=59, second=59) # 週日 23:59:59
        
        # 若該週末已過 (雖前段有位移保護，這裡雙重確保)
        if end_dt < base_dt:
            start_dt += timedelta(days=7)
            end_dt += timedelta(days=7)
            
        return {
            "field": "time",
            "value": [start_dt.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S")],
            "cmp": "between",
            "constraint_level": constraint_level,
            "weight": weight
        }

    # 7. Fallback: 無法解析具體時間時，回傳偏移後日期的 23:59:59，維持 open_at
    target_dt = target_dt.replace(hour=23, minute=59, second=59)
    return {
        "field": "time",
        "value": [target_dt.strftime("%Y-%m-%d %H:%M:%S")],
        "cmp": "open_at",
        "constraint_level": constraint_level,
        "weight": weight
    }

def _parse_distance(text):
    """
    輔助函式：從字串中提取距離並轉換為公尺 (m)。
    支援阿拉伯數字與基礎中文數字轉換。
    """
    match = re.search(r'([零一二兩三四五六七八九十百千0-9.]+)\s*(公里|公尺|km|m|米)', text, re.IGNORECASE)
    if not match:
        return None
        
    num_str = match.group(1)
    unit = match.group(2).lower()
    
    val = 0.0
    if re.match(r'^[0-9.]+$', num_str):
        val = float(num_str)
    else:
        ch_nums = {'零':0, '一':1, '二':2, '兩':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9, '十':10}
        if '千' in num_str:
            val = ch_nums.get(num_str.split('千')[0], 1) * 1000
        elif '百' in num_str:
            val = ch_nums.get(num_str.split('百')[0], 1) * 100
        else:
            val = ch_nums.get(num_str, 0)
            
    if unit in ['公里', 'km']:
        val *= 1000
        
    return int(val)

def parse_address_logic(user_address_input, index=0):
    """
    將使用者的口語地址或地點描述轉換為系統 Logic Tree 2.0 規格的條件字典。

    判定是否為精確地址（路/街/區/里，或純行政區如「永康」、「新化」）
    或是地標附近的範圍搜尋（near）。
    為確保資料庫精確過濾，行政區匹配 (cmp: "=") 時禁止出現 distance 欄位。
    當 cmp 為 near 時，會自動嵌入環境變數定義的 distance。

    參數:
        user_address_input (str): 使用者輸入的地點文字。
        index (int): 條件順序，預設為 0。
    """
    constraint_level, weight = _calculate_intensity_and_weight(user_address_input, index)

    dist_val = _parse_distance(user_address_input)

    exact_pattern = r"[路街巷弄段區里市]"
    near_keywords = ["附近", "周邊", "旁邊", "靠近", "以內", "方圓"]

    address_vocab = VOCAB.get("address", [])
    has_vocab_address = any(addr in user_address_input for addr in address_vocab)

    # 實施【MY_LOCATION 雙軌判定鎖】
    track1_keywords = ["我附近", "這附近", "我旁邊", "我周邊", "身邊", "當前位置"]
    track2_keywords = ["附近", "周邊", "旁邊"]
    
    is_track1 = any(kw in user_address_input for kw in track1_keywords)
    is_track2 = (any(kw in user_address_input for kw in track2_keywords) and 
                 not has_vocab_address and 
                 re.search(exact_pattern, user_address_input) is None)

    if is_track1 or is_track2:
        return {
            "field": "address",
            "value": ["MY_LOCATION"],
            "cmp": "near",
            "constraint_level": constraint_level,
            "weight": weight,
            "distance": dist_val if dist_val is not None else DEFAULT_SEARCH_DISTANCE
        }

    if dist_val is not None:
        cmp_op = "near"
    elif any(kw in user_address_input for kw in near_keywords):
        cmp_op = "near"
    elif re.search(exact_pattern, user_address_input) or has_vocab_address:
        cmp_op = "="
    else:
        # 只有純地標名稱
        cmp_op = "near"

    logic_node = {
        "field": "address",
        "value": [user_address_input],
        "cmp": cmp_op,
        "constraint_level": constraint_level,
        "weight": weight
    }

    if cmp_op == "near":
        logic_node["distance"] = dist_val if dist_val is not None else DEFAULT_SEARCH_DISTANCE

    return logic_node

def parse_rating_logic(user_rating_input, index=0):
    """
    將使用者的口語評分轉換為數值，並輸出成 Logic Tree 2.0 規格。

    支援處理「四顆星」、「滿分」、「五星好評」等豐富語意，並將其轉換為 float。
    具備運算子判定（>=, <=, =）與數值截斷機制（最高 5.0）。

    參數:
        user_rating_input (str): 使用者輸入的評分文字。
        index (int): 條件順序，預設為 0。
    """
    constraint_level, weight = _calculate_intensity_and_weight(user_rating_input, index)
    
    # 1. 預處理模組：將中文數字轉為阿拉伯數字 (一~五 -> 1~5)
    ch_nums = {'一': '1', '二': '2', '兩': '2', '三': '3', '四': '4', '五': '5'}
    processed_input = user_rating_input
    for ch, num in ch_nums.items():
        processed_input = processed_input.replace(ch, num)
        
    # 2. 關鍵字映射與數值提取
    rating_val = 4.0  # 預設備援 4.0
    if any(kw in processed_input for kw in ["滿分", "五星好評", "5星好評"]):
        rating_val = 5.0
    else:
        # 3. 使用 Regex 提取浮點數或整數
        match = re.search(r'(\d+(?:\.\d+)?)', processed_input)
        if match:
            rating_val = float(match.group(1))
            
    # 4. 數值截斷 (Clamping)：符合餐飲評分常規，最高為 5.0
    if rating_val > 5.0:
        rating_val = 5.0
        
    # 5. 運算子判定進化
    cmp_op = ">="
    if any(kw in processed_input for kw in ["剛好", "等於", "不多不少"]):
        cmp_op = "="
    elif any(kw in processed_input for kw in ["低於", "不到", "不超過"]):
        cmp_op = "<="

    return {
        "field": "rating",
        "value": [rating_val],
        "cmp": cmp_op,
        "constraint_level": constraint_level,
        "weight": weight
    }

def parse_restaurant_type_logic(user_input, index=0):
    """
    將使用者對於「經營型態」的口語描述轉換為 Logic Tree 2.0 規格。
    例如：「路邊攤」、「餐廳」等。這與 food_type (食物種類) 是獨立維度，
    可以在 Logic Tree 中並存，例如 AND(restaurant_type='路邊攤', food_type='牛肉湯')。

    參數:
        user_input (str): 使用者輸入的經營型態文字。
        index (int): 條件順序，預設為 0。
    """
    constraint_level, weight = _calculate_intensity_and_weight(user_input, index)

    return {
        "field": "restaurant_type",
        "value": [user_input],
        "cmp": "=",
        "constraint_level": constraint_level,
        "weight": weight
    }