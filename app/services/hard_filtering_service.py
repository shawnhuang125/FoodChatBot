import json
import pytz
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.utils.app_logger import logger

class HardFilteringService:
    def __init__(self):
        self.default_tz = pytz.timezone('Asia/Taipei')
        self.week_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

    def filter_by_business_hours(
        self, 
        db_results: List[Dict[str, Any]], 
        target_time: Optional[str] = None,
        s_id: str = "unknown"
    ) -> List[Dict[str, Any]]:
        """
        第四階段：營業時間過濾（整合單一函式版本）
        """
        # 【步驟 1】紀錄原始店家總筆數
        original_count = len(db_results)
        filtered_results = []
        
        # 【步驟 1】嚴格的時間檢查：未提供 target_time 則直接結束
        if not target_time:
            logger.warning(f"[Hard Filtering][SID: {s_id}] 缺少必要參數 target_time，跳過過濾，輸出原始資料。")
            return db_results  # 原封不動輸出
            
        # 【步驟 2】格式解析：解析錯誤則跳過過濾，原封不動輸出
        try:
            dt = datetime.strptime(target_time, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.error(f"[Hard Filtering][SID: {s_id}] target_time 格式錯誤 ({target_time})，跳過過濾，輸出原始資料。")
            return db_results  # 原封不動輸出
        
        # 轉換時間數值與當天星期 Key
        today_str = self.week_map[dt.weekday()]
        current_time = dt.hour * 100 + dt.minute
        
        # 【步驟 3】進入迴圈：逐筆過濾店家資料
        for row in db_results:
            opening_hours = row.get("opening_hours", {})
            is_open = False  # 預設此店家為未營業
            
            # 3.1 檢查輸入是否為字串，若是則嘗試解析為字典
            if isinstance(opening_hours, str):
                try:
                    opening_hours = json.loads(opening_hours)
                except json.JSONDecodeError:
                    # 解析失敗，保持 is_open = False，直接處理下一家
                    continue
                    
            # 3.2 確保型態為字典，否則判定不營業
            if not isinstance(opening_hours, dict):
                continue

            # 3.3 擷取店家在今天的營業時間字串
            time_str = opening_hours.get(today_str, "休息")
            
            # 3.4 特殊狀態判斷一：24 小時營業
            if "24 小時" in str(time_str):
                is_open = True
                
            # 3.5 特殊狀態判斷二：休息或空值
            elif not time_str or time_str == "休息": 
                is_open = False
            
            # 3.6 一般時段拆解與區間比對
            else:
                for interval in str(time_str).split(','):
                    try:
                        start_str, end_str = interval.split('-')
                        start_h, start_m = map(int, start_str.strip().split(':'))
                        end_h, end_m = map(int, end_str.strip().split(':'))
                        
                        start_time_num = start_h * 100 + start_m
                        end_time_num = end_h * 100 + end_m
                        
                        # 判斷當前時間是否落在營業區間內
                        if start_time_num <= current_time <= end_time_num:
                            is_open = True
                            break  # 符合任一時段，立刻跳出時段比對迴圈
                    except Exception: 
                        continue  # 格式解析出錯則跳過該時段
            
            # 3.7 根據最終判定結果決定是否保留店家
            if is_open:
                filtered_results.append(row)
                
        # 【步驟 4】計算過濾後總筆數並寫入 Log 日誌
        filtered_count = len(filtered_results)
        logger.info(
            f"[Hard Filtering][SID: {s_id}] 營業時間過濾完成：從 {original_count} 筆縮減至 {filtered_count} 筆 "
            f"(過濾掉 {original_count - filtered_count} 筆未營業店家)"
        )
        
        # 【步驟 5】回傳有效營業店家列表
        return filtered_results