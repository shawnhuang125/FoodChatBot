# app/service/hard_filtering_service.py
import json
import pytz
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.utils.app_logger import logger

class HardFilteringService:
    def __init__(self):
        self.default_tz = pytz.timezone('Asia/Taipei')
        self.week_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

    def is_open_now(self, opening_hours: Any, target_time: Optional[str] = None) -> bool:
        if isinstance(opening_hours, str):
            try:
                opening_hours = json.loads(opening_hours)
            except json.JSONDecodeError:
                return False
                
        if not isinstance(opening_hours, dict):
            return False

        if target_time:
            try:
                dt = datetime.strptime(target_time, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                dt = datetime.now(self.default_tz)
        else:
            dt = datetime.now(self.default_tz)
        
        today_str = self.week_map[dt.weekday()]
        time_str = opening_hours.get(today_str, "休息")
        
        if "24 小時" in str(time_str):
            return True
            
        if not time_str or time_str == "休息": 
            return False
        
        current_time = dt.hour * 100 + dt.minute
        
        for interval in str(time_str).split(','):
            try:
                start_str, end_str = interval.split('-')
                start_h, start_m = map(int, start_str.strip().split(':'))
                end_h, end_m = map(int, end_str.strip().split(':'))
                
                if (start_h * 100 + start_m) <= current_time <= (end_h * 100 + end_m):
                    return True
            except Exception: 
                continue
                
        return False

    def filter_by_business_hours(
        self, 
        db_results: List[Dict[str, Any]], 
        target_time: Optional[str] = None,
        s_id: str = "unknown"
    ) -> List[Dict[str, Any]]:
        """
        批次過濾未營業的店家列表，並詳細記錄日誌
        """
        original_count = len(db_results)
        
        filtered_results = [
            row for row in db_results
            if self.is_open_now(row.get("opening_hours", {}), target_time=target_time)
        ]
        
        filtered_count = len(filtered_results)
        logger.info(
            f"[Hard Filtering][SID: {s_id}] 營業時間過濾完成：從 {original_count} 筆縮減至 {filtered_count} 筆 "
            f"(過濾掉 {original_count - filtered_count} 筆未營業店家)"
        )
        return filtered_results