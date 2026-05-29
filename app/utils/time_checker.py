import json  # 🟢 務必匯入 json
from datetime import datetime
import pytz

def is_open_now(opening_hours: str, target_time: str = None) -> bool:
    # 🟢 1. 如果它是字串，先轉成字典
    if isinstance(opening_hours, str):
        try:
            opening_hours = json.loads(opening_hours)
        except json.JSONDecodeError:
            return False  # 如果格式不是 JSON，視為關門
            
    # 如果它是 None 或非 dict，直接返回 False
    if not isinstance(opening_hours, dict):
        return False

    # 🟢 2. 後續的時間判斷邏輯保持不變
    if target_time:
        dt = datetime.strptime(target_time, '%Y-%m-%d %H:%M:%S')
    else:
        tw_tz = pytz.timezone('Asia/Taipei')
        dt = datetime.now(tw_tz)
    
    week_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    today_str = week_map[dt.weekday()]
    
    time_str = opening_hours.get(today_str, "休息")
    
    # 這裡處理 "24 小時營業" 的特殊情況
    if "24 小時" in str(time_str):
        return True
        
    if not time_str or time_str == "休息": 
        return False
    
    current_time = dt.hour * 100 + dt.minute
    
    for interval in time_str.split(','):
        try:
            start_str, end_str = interval.split('-')
            start_h, start_m = map(int, start_str.strip().split(':'))
            end_h, end_m = map(int, end_str.strip().split(':'))
            
            if (start_h * 100 + start_m) <= current_time <= (end_h * 100 + end_m):
                return True
        except: continue
    return False