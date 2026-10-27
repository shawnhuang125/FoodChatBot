# app/services/hard_filtering_service.py
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from app.utils.app_logger import logger


class HardFilteringService:

  def __init__(self):
    self.week_map = [
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
    ]

  def filter_by_business_hours(
      self,
      db_results: List[Dict[str, Any]],
      target_time: Optional[Dict[str, Any]] = None,
      s_id: str = "unknown",
  ) -> List[Dict[str, Any]]:
    if not db_results or not target_time:
      return db_results

    logger.info(
        f"[Hard Filtering][SID: {s_id}] 開始執行過濾 | 輸入資料筆數:"
        f" {len(db_results)}"
    )

    all_requirements = []

    def recursive_extract(node, key=None):
      if not isinstance(node, dict):
        return
      if node.get("field") == "time":
        vals = node.get("value", [])
        cmp = str(node.get("cmp", "open_at")).lower()

        if not isinstance(vals, list) or not vals:
          logger.warning(
              f"[Hard Filtering][SID: {s_id}] 無效的時間格式: {vals}"
          )
          return

        def parse_time_to_int(time_str: str):
          """處理 '(星期X) HH:MM:SS' 格式的解析器"""
          parts = time_str.split(") ")
          if len(parts) < 2:
            raise ValueError(
                f"格式不符: 無法正確分割星期與時間: {time_str}"
            )

          w = parts[0].replace("(", "").replace("禮拜", "星期")
          time_part = parts[1].split(":")
          h, m = int(time_part[0]), int(time_part[1])
          return w, h * 100 + m

        try:
          w, u_start = parse_time_to_int(str(vals[0]))
          u_end = u_start

          if cmp == "between" and len(vals) >= 2:
            _, u_end = parse_time_to_int(str(vals[1]))
            if u_end < u_start:
              u_end += 2400

          all_requirements.append({
              "weekday": w,
              "start": u_start,
              "end": u_end,
              "is_point": (cmp != "between" or u_start == u_end),  # 標記是否為單點時間
          })

        except (ValueError, IndexError, AttributeError) as e:
          logger.error(
              f"[Hard Filtering][SID: {s_id}] 時間解析異常 | 資料: {vals} |"
              f" 錯誤: {e}"
          )

      for k, val in node.items():
        if isinstance(val, dict):
          recursive_extract(val, k)
        elif isinstance(val, list):
          is_condition_list = k in ["conditions", "sub_conditions"]
          for item in val:
            if isinstance(item, dict):
              recursive_extract(item, k)
            elif is_condition_list:
              logger.error(
                  f"[Hard Filtering][SID: {s_id}] 關鍵清單格式錯誤 | 欄位: {k} |"
                  f" 預期 dict，收到: {type(item)}"
              )

    recursive_extract(target_time)
    if not all_requirements:
      return db_results

    filtered_results = []
    global_op = target_time.get("op", "AND").upper()

    for row in db_results:
      opening_hours = row.get("opening_hours", {})
      if isinstance(opening_hours, str):
        try:
          opening_hours = json.loads(opening_hours)
        except Exception:
          continue

      def check_row():
        results = []
        for req in all_requirements:
          day_hours = opening_hours.get(req["weekday"], "休息")
          if "24 小時" in str(day_hours):
            results.append(True)
            continue
          if not day_hours or day_hours == "休息":
            results.append(False)
            continue

          intervals = []
          for interval in str(day_hours).split(","):
            try:
              s, e = interval.split("-")
              s_int = int(s.split(":")[0]) * 100 + int(s.split(":")[1])
              e_int = int(e.split(":")[0]) * 100 + int(e.split(":")[1])
              if e_int < s_int:
                e_int += 2400
              intervals.append((s_int, e_int))
            except Exception:
              continue

          # 修正判斷邏輯：區分「單點時間 open_at」與「時間區間 between」
          if req["is_point"]:
            target_t = req["start"]
            # 單點時間：只要該點落在任一營業時段內即符合 (s <= target <= e)
            is_open = any(s <= target_t <= e for s, e in intervals)
          else:
            # 區間重疊：兩個區間有交集
            is_open = any(
                max(req["start"], s) <= min(req["end"], e) for s, e in intervals
            )

          results.append(is_open)

        return any(results) if global_op == "OR" else all(results)

      if check_row():
        filtered_results.append(row)

    logger.info(
        f"[Hard Filtering][SID: {s_id}] 過濾完成 | 剩餘: {len(filtered_results)}"
    )
    return filtered_results