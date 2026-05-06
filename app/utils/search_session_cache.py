# app/utils/search_session_cache.py
import json
import math
import logging
from decimal import Decimal  # 1. 引入 Decimal
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as aioredis

from app.config import Config


import secrets
import string

def generate_short_ssid(length=6):
    # 生成包含大寫字母與數字的隨機碼 (例如: A7B2X9)
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# 2. 定義自定義 Encoder 處理 Decimal
class DecimalEncoder(json.JSONEncoder):
    """
    處理 Python json 庫預設不支援 Decimal 的問題。
    將 Decimal 轉為 float (適合座標/距離) 或 str (適合高精度金額)。
    """
    def default(self, obj):
        if isinstance(obj, Decimal):
            # 這裡建議轉為 float，因為搜尋結果多為座標或評分
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


class SearchSessionCache:
    """
    負責管理搜尋結果的 Redis 分頁快取。
    """

    KEY_PREFIX = "search_session"

    def __init__(self):
        self._pool = aioredis.ConnectionPool(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=Config.REDIS_DB,
            password=Config.REDIS_PASSWORD,
            decode_responses=True,
            max_connections=20
        )
        self._redis = aioredis.Redis(connection_pool=self._pool)

    def _build_key(self, search_ssid: str) -> str:
        return f"{self.KEY_PREFIX}:{search_ssid}"
    
    def _generate_short_ssid(self, length=6):
        # 生成包含大寫字母與數字的隨機碼 (例如: A7B2X9)
        alphabet = string.ascii_uppercase + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    # ── 公開 API ──────────────────────────────────────────────────

    
    async def create_session_and_get_first_page(
        self, 
        all_results: List[Dict[str, Any]], 
        page_size: int = None
    ) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        """
        [統一封裝門面] 
        1. 生成 6 碼隨機 SSID
        2. 將全量資料存入 Redis (處理過 Decimal)
        3. 立即切出第 1 頁並回傳
        
        回傳: (search_ssid, first_page_results, pagination_meta)
        """
        # 1. 生成 SSID
        search_ssid = self._generate_short_ssid(6)
        
        # 2. 存入 Redis (利用類別內已有的 save 邏輯)
        await self.save(search_ssid, all_results)
        
        # 3. 取得第 1 頁 (利用類別內已有的 get_page 邏輯)
        page_results, pagination_meta = await self.get_page(
            search_ssid, page=1, page_size=page_size
        )
        
        return search_ssid, page_results, pagination_meta

    # ── 以下原始方法保持不變，但可被內部調用 ──────────────────────────────

    async def save(self, search_ssid: str, all_results: List[Dict[str, Any]], ttl: int = None) -> None:
        effective_ttl = ttl if ttl is not None else Config.SEARCH_SESSION_TTL
        key = self._build_key(search_ssid)
        try:
            serialized = json.dumps(all_results, ensure_ascii=False, cls=DecimalEncoder)
            await self._redis.set(key, serialized, ex=effective_ttl)
            logging.info(f"[SessionCache] 已儲存 Session '{search_ssid}'，共 {len(all_results)} 筆")
        except Exception as e:
            logging.error(f"[SessionCache] 儲存失敗: {e}")
            raise
        

    async def save(
        self,
        search_ssid: str,
        all_results: List[Dict[str, Any]],
        ttl: int = None
    ) -> None:
        """
        將全量排序結果序列化後存入 Redis，並設定 TTL。
        """
        effective_ttl = ttl if ttl is not None else Config.SEARCH_SESSION_TTL
        key = self._build_key(search_ssid)

        try:
            # 3. 在這裡傳入 cls=DecimalEncoder
            serialized = json.dumps(
                all_results, 
                ensure_ascii=False, 
                cls=DecimalEncoder
            )
            await self._redis.set(key, serialized, ex=effective_ttl)
            logging.info(
                f"[SessionCache] 已儲存 Session '{search_ssid}'，"
                f"共 {len(all_results)} 筆，TTL={effective_ttl}s"
            )
        except Exception as e:
            logging.error(f"[SessionCache] 儲存 Session '{search_ssid}' 失敗: {e}")
            raise

    async def get_page(
        self,
        search_ssid: str,
        page: int,
        page_size: int = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        從 Redis 取出指定頁的店家資料，同時回傳分頁元數據。
        """
        effective_size = page_size if page_size is not None else Config.PAGE_SIZE
        key = self._build_key(search_ssid)

        try:
            raw = await self._redis.get(key)
        except Exception as e:
            logging.error(f"[SessionCache] 讀取 Session '{search_ssid}' 失敗: {e}")
            raise

        if raw is None:
            logging.warning(f"[SessionCache] Session '{search_ssid}' 不存在或已過期")
            return [], {"error": "session_expired"}

        # json.loads 不需要特別處理，因為讀回來的已經是 JSON 格式中的 number/string
        all_results: List[Dict] = json.loads(raw)
        total_results = len(all_results)
        total_pages = math.ceil(total_results / effective_size) if total_results > 0 else 0

        clamped_page = max(1, min(page, total_pages)) if total_pages > 0 else 1

        start = (clamped_page - 1) * effective_size
        end = start + effective_size
        page_results = all_results[start:end]

        meta = {
            # 翻頁用的 Session 識別碼
            # 為什麼放在 pagination 裡：生成式模型只需看 data.pagination 就能拿到
            # 翻頁所需的全部資訊（ssid + page），不需要跨層去頂層找 s_id，降低對應錯誤的風險
            # 使用方式：GET /place_search/page?search_ssid={此值}&page=N
            "search_ssid": search_ssid,
            "current_page": clamped_page,
            "total_pages": total_pages,
            "total_results": total_results,
            "page_size": effective_size,
            "session_ttl_seconds": Config.SEARCH_SESSION_TTL
        }

        logging.info(
            f"[SessionCache] 取得 Session '{search_ssid}' 第 {clamped_page}/{total_pages} 頁，"
            f"回傳 {len(page_results)} 筆"
        )
        return page_results, meta

    async def exists(self, search_ssid: str) -> bool:
        key = self._build_key(search_ssid)
        try:
            return bool(await self._redis.exists(key))
        except Exception as e:
            logging.error(f"[SessionCache] 檢查 Session '{search_ssid}' 存活失敗: {e}")
            return False

    async def delete(self, search_ssid: str) -> None:
        key = self._build_key(search_ssid)
        try:
            await self._redis.delete(key)
            logging.info(f"[SessionCache] 已手動刪除 Session '{search_ssid}'")
        except Exception as e:
            logging.error(f"[SessionCache] 刪除 Session '{search_ssid}' 失敗: {e}")
            raise

    async def close(self) -> None:
        await self._redis.aclose()
        logging.info("[SessionCache] Redis 連線池已關閉")