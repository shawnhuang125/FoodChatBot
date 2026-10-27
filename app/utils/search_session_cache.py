# app/utils/search_session_cache.py
import json
import math
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as aioredis
from app.config import Config

import secrets
import string


def generate_short_ssid(length=6):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class DecimalEncoder(json.JSONEncoder):
    """
    處理 Python json 庫預設不支援 Decimal 的問題。
    """
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


class SearchSessionCache:
    """
    負責管理搜尋結果的 Redis 分頁快取。
    - 存儲：全量原始完整資料
    - POST 檢索 (create_session_and_get_first_page)：回傳【完整資料】
    - GET 翻頁 (get_page)：從 Redis 取出後回傳【精簡資料】
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
        alphabet = string.ascii_uppercase + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def _extract_lightweight_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """
        【翻頁專用】從完整物件中擷取輕量化展示欄位：
        - place_id (對應系統內部 all_places.id)
        - 店家名稱 (對應 SQL 的 restaurant_name)
        - rating
        - price_level
        - merchant_category
        - distance (距離)
        - 第一張照片的連結內容 (photo_url)
        - 排序/推薦理由 (ranking_reason)
        """
        # 1. 唯一識別碼：對應系統內部 id (all_places.id)
        place_id = item.get("id") or item.get("place_id")

        # 2. 店家名稱：優先取 SQL 生成的 restaurant_name 別名
        restaurant_name = item.get("restaurant_name") 
  
        # 3. 評分、價位、分類
        rating = item.get("rating")
        price_level = item.get("price_level")
        merchant_category = item.get("merchant_category") or item.get("category")

        # 4. 🟢 距離處理 (若有計算出距離則取用，可格式化取小數點後兩位)
        distance = item.get("distance")
        if distance is not None:
            try:
                distance = round(float(distance), 2)
            except (ValueError, TypeError):
                pass

        # 5. 第一張照片處理
        primary_photo_url = None
        photos = item.get("photos") or item.get("photo_urls") or item.get("images")

        if isinstance(photos, list) and len(photos) > 0:
            first_photo = photos[0]
            if isinstance(first_photo, dict):
                primary_photo_url = (
                    first_photo.get("url")
                    or first_photo.get("photo_url")
                    or first_photo.get("photo_reference")
                )
            elif isinstance(first_photo, str):
                primary_photo_url = first_photo
        elif isinstance(item.get("photo_url"), str):
            primary_photo_url = item.get("photo_url")

        # 6. 排序 / 推薦理由
        ranking_reason = item.get("ranking_reason")

        return {
            "place_id": place_id,
            "restaurant_name": restaurant_name,
            "rating": rating,
            "price_level": price_level,
            "merchant_category": merchant_category,
            "distance": distance,
            "photo_url": primary_photo_url,
            "ranking_reason": ranking_reason,
        }

    # ── 公開 API ──────────────────────────────────────────────────

    async def create_session_and_get_first_page(
        self, 
        all_results: List[Dict[str, Any]], 
        page_size: int = None
    ) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        """
        [POST /place_search 專用門面] 
        1. 生成 6 碼隨機 SSID
        2. 全量資料【完整原樣】存入 Redis
        3. 切出第 1 頁【完整原樣資料】直接回傳（不經過精簡）
        """
        effective_size = page_size if page_size is not None else Config.PAGE_SIZE
        search_ssid = self._generate_short_ssid(6)
        
        # 1. 存入完整資料至 Redis
        await self.save(search_ssid, all_results)
        
        # 2. 直接切出第 1 頁的完整未刪減資料
        total_results = len(all_results)
        total_pages = math.ceil(total_results / effective_size) if total_results > 0 else 0
        first_page_results = all_results[:effective_size]

        pagination_meta = {
            "search_ssid": search_ssid,
            "current_page": 1,
            "total_pages": total_pages,
            "total_results": total_results,
            "page_size": effective_size,
            "session_ttl_seconds": Config.SEARCH_SESSION_TTL
        }
        
        return search_ssid, first_page_results, pagination_meta

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
            serialized = json.dumps(
                all_results, 
                ensure_ascii=False, 
                cls=DecimalEncoder
            )
            await self._redis.set(key, serialized, ex=effective_ttl)
            logging.info(
                f"[SessionCache] 已儲存 Session '{search_ssid}'，"
                f"共 {len(all_results)} 筆完整資料，TTL={effective_ttl}s"
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
        【GET /place_search/page 翻頁端點專用】
        從 Redis 取出指定頁資料，並轉為【精簡格式】回傳。
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

        all_results: List[Dict] = json.loads(raw)
        total_results = len(all_results)
        total_pages = math.ceil(total_results / effective_size) if total_results > 0 else 0

        clamped_page = max(1, min(page, total_pages)) if total_pages > 0 else 1

        start = (clamped_page - 1) * effective_size
        end = start + effective_size
        
        # 翻頁才轉成精簡欄位
        page_results = [
            self._extract_lightweight_item(item)
            for item in all_results[start:end]
        ]

        meta = {
            "search_ssid": search_ssid,
            "current_page": clamped_page,
            "total_pages": total_pages,
            "total_results": total_results,
            "page_size": effective_size,
            "session_ttl_seconds": Config.SEARCH_SESSION_TTL
        }

        logging.info(
            f"[SessionCache] 取得 Session '{search_ssid}' 第 {clamped_page}/{total_pages} 頁，"
            f"精簡回傳 {len(page_results)} 筆"
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