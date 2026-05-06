# app/repository/rdbms_repository.py
import time
import asyncio
from typing import List, Dict, Any, Tuple 
import logging
import aiomysql  
from app.utils.app_logger import logger

from app.utils.db import get_async_db_pool 

class RdbmsRepository:
    def __init__(self, use_mock: bool = False):
        logger.info("[RDBMS Repo] 初始化模式: REAL DB (Async)")

    # 這裡加入 s_id 參數，預設為 None 增加相容性
    async def execute_dynamic_query(self, sql: str, params: Dict[str, Any], s_id: str = None) -> Tuple[List[Dict[str, Any]], float]:
        """
        執行動態 SQL 查詢並回傳結果與執行時間。
        合併了原始的 _execute_real_db 邏輯。
        """
        start_time = time.time()
        log_prefix = f"[RDBMS Repo][SID: {s_id}]" if s_id else "[RDBMS Repo]"
        
        try:
            pool = await get_async_db_pool()
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    
                    # 1. Log 記錄 (參數內容與型別檢查對除錯非常有幫助)
                    logger.info(f"{log_prefix} 執行 SQL: {sql}")
                    param_info = ", ".join([f"{k}: {v} ({type(v).__name__})" for k, v in params.items()])
                    logger.info(f"{log_prefix} 綁定參數: {param_info}")
                    
                    # 2. 執行查詢
                    await cursor.execute(sql, params)
                    records = await cursor.fetchall()
                    
                    # 3. 計算執行時間
                    execution_time = time.time() - start_time
                    
                    # 4. 結果診斷
                    if records:
                        logger.info(f"{log_prefix} 取得第一筆資料範例: {records[0]}")
                    else:
                        logger.warning(f"{log_prefix} 查詢結果為空，請確認資料庫是否有對應資料")
                    
                    logger.info(f"{log_prefix} 成功取得 {len(records)} 筆資料，耗時: {execution_time:.5f}秒")
                    return list(records), execution_time

        except aiomysql.Error as e:
            logger.error(f"{log_prefix} 資料庫層級錯誤: {e}")
            return [], 0.0
        except Exception as e:
            logger.error(f"{log_prefix} 系統程式碼錯誤: {e}")
            return [], 0.0