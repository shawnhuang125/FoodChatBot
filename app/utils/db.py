# app/utils/db.py
from qdrant_client import AsyncQdrantClient
import aiomysql
import asyncio
import logging
from app.config import Config

# 全域變數，用於儲存連線池實例與同步鎖
_db_pool = None
_qdrant_client = None
_db_lock = asyncio.Lock()

async def get_async_db_pool():
    """
    獲取或初始化非同步資料庫連線池。
    使用 Double-Checked Locking 模式確保併發安全性。
    """
    global _db_pool
    
    # 第一次檢查：若已初始化則直接回傳，避免進入鎖競爭
    if _db_pool is not None:
        return _db_pool

    # 第二次檢查：進入鎖定狀態，確保只有一個協程能執行初始化過程
    async with _db_lock:
        if _db_pool is None:
            try:
                logging.info("[DB Utils] 正在初始化 aiomysql 連線池...")
                _db_pool = await aiomysql.create_pool(
                    host=Config.DB_HOST,
                    port=Config.DB_PORT,
                    user=Config.DB_USER,
                    password=Config.DB_PASSWORD,
                    db=Config.DB_NAME,
                    minsize=5,       # 池中保持的最小連線數
                    maxsize=20,      # 池中允許的最大連線數
                    autocommit=True, # 自動提交事務
                    charset="utf8mb4"
                )
                logging.info("[DB Utils] 連線池初始化成功 (Pre-warmed: 5 connections)")
            except Exception as e:
                logging.error(f"[DB Utils] 連線池初始化失敗: {e}")
                raise e
    return _db_pool


async def get_qdrant_client():
    """獲取 Qdrant 非同步客戶端單例"""
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    
    async with _db_lock:
        if _qdrant_client is None:
            try:
                logging.info(f"[Vector DB] 初始化 Qdrant 連線: {Config.VECTOR_DB_HOST}")
                _qdrant_client = AsyncQdrantClient(
                    host=Config.VECTOR_DB_HOST,
                    port=int(Config.VECTOR_DB_PORT),
                    prefer_grpc=False
                )
            except Exception as e:
                logging.error(f"[Vector DB] Qdrant 初始化失敗: {e}")
                raise e
    return _qdrant_client


async def close_all_connections():
    """在 shutdown 時呼叫，一次關閉 MySQL 與 Qdrant"""
    global _db_pool, _qdrant_client
    
    # 關閉 MySQL
    if _db_pool is not None:
        _db_pool.close()
        await _db_pool.wait_closed()
        _db_pool = None
        logging.info("[DB] MySQL 已關閉")

    # 關閉 Qdrant
    if _qdrant_client is not None:
        # Qdrant Client 內部通常會自動處理關閉，但主動執行 closes() 是更好的做法
        await _qdrant_client.close()
        _qdrant_client = None
        logging.info("[DB] Qdrant 已關閉")