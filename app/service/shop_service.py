# ./app/services/shop_services.py
import os
import json
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, literal_column
from app.models.models import Restaurant
from app.service.photo_service import PhotoService  
from app.utils.distance_utils import get_haversine_distance_sql, format_distance
from app.logger import logger
from app.config import Config

class ShopService:
    # 設施排序與過濾定義
    FACILITY_ORDER = ["內用", "外帶", "冷氣", "吃到飽", "特約停車場"]

    def __init__(self, db: Session):
        self.db = db
        # 圖片邏輯委派給專業的 PhotoService 處理
        self.photo_service = PhotoService()

    def _is_valid_coordinate(self, coord_str: str) -> bool:
        """直接使用字串檢查，不會發生 0 被切掉的問題"""
        if '.' not in coord_str:
            return False
        
        decimal_part = coord_str.split('.')[1]
        return len(decimal_part) >= 5

    def get_shop_info(self, pid: int, user_lat: Optional[str] = None, user_lng: Optional[str] = None):
        """
        接收前端輸入:
        店家pid與
        當前手機的lat
        當前手機的lng
        """

        # 1. 檢查參數是否完整
        if user_lat is None or user_lng is None:
            raise ValueError("經緯度必須完整提供")

        # 2. 檢查精確度
        if not self._is_valid_coordinate(user_lat) or not self._is_valid_coordinate(user_lng):
            # 拋出錯誤，讓 Controller 轉成 400
            raise ValueError("座標精確度不足 (未達 5 位)")

        # 3. 轉型與查詢
        lat_f, lng_f = float(user_lat), float(user_lng)
        
        logger.info(f"[ShopService] 開始獲取店家資訊 | PID: {pid} | User座標: ({lat_f}, {lng_f})")

        shop, distance = self._fetch_shop(pid, lat_f, lng_f)
        if not shop:
            return None

        # 這裡 getattr 已經把資料從資料庫 Column 轉成了真正的 Python 原生型別 (int/str)
        shop_dict = {c.name: getattr(shop, c.name) for c in shop.__table__.columns}

        # 把計算出來的距離塞進字典裡 (如果有傳座標的話)
        shop_dict['distance'] = format_distance(distance) if distance is not None else None

        if distance is not None:
            logger.info(f"[ShopService] 距離計算完成 | 店名: {shop.name} | 距離: {shop_dict['distance']} ")
        else:
            logger.debug(f"[ShopService] 未提供座標，跳過距離計算 | 店名: {shop.name}")
        
        # 1. 處理 JSON 欄位
        shop_dict['opening_hours'] = self._parse_json(shop_dict.get('opening_hours'))
        
        # 2. 處理標籤與屬性
        self._inject_attributes(shop, shop_dict)

        # 3. 呼叫 PhotoService 獲取圖片 URL 清單
        # 傳入 shop_dict['id'] (int)，完全避開 SQLAlchemy Column 型別問題
        shop_dict['photos'] = self.photo_service.get_shop_photos(shop_dict['id'])
        
        return shop_dict

    def _fetch_shop(self, pid: int, user_lat: Optional[float], user_lng: Optional[float]):
        """私有方法：負責資料庫查詢，若有座標則計算距離"""

        # 如果使用者有傳送經緯度，我們就把距離 SQL 加上去
        if user_lat is not None and user_lng is not None:

            logger.debug(f"[ShopService] 執行 SQL 距離查詢 (Haversine Formula) | User: ({user_lat}, {user_lng})")

            # 取得 SQL 字串 (注意：這裡的 lat_col 和 lng_col 要確認你的資料表欄位名稱是不是 lat 和 lng)
            sql_str = get_haversine_distance_sql(
                user_lat=user_lat, 
                user_lng=user_lng, 
                lat_col="all_places.lat", 
                lng_col="all_places.lng"
            )

            # 轉成 SQLAlchemy 的 literal_column 格式
            distance_expr = literal_column(sql_str).label("distance")
            
            # 查詢實體 + 距離
            result = self.db.query(Restaurant, distance_expr)\
                .options(joinedload(Restaurant.attributes))\
                .filter(Restaurant.id == pid)\
                .first()
                
            if result:
                return result[0], result[1] # 回傳 (shop實體, distance數字)
            return None, None
            
        else:
            # 如果沒有傳座標，就走原本單純查詢實體的邏輯
            logger.debug(f"[ShopService] 執行一般店家查詢 (無座標) | PID: {pid}")
            shop = self.db.query(Restaurant)\
                .options(joinedload(Restaurant.attributes))\
                .filter(Restaurant.id == pid)\
                .first()
            return shop, None


    def _parse_json(self, data: Any) -> Dict:
        """私有方法：負責安全的 JSON 解析"""
        if not data: return {}
        try:
            return json.loads(data) if isinstance(data, str) else data
        except:
            return {}

    def _inject_attributes(self, shop: Restaurant, shop_dict: Dict[str, Any]):
        """私有方法：處理標籤合併與設施排序"""
        if not shop.attributes:
            shop_dict.update({'attributes_tags': [], 'merchant_category': None, 'facility_tags': []})
            return

        # 標籤合併
        tags = []
        for source in [shop.attributes.food_type, shop.attributes.cuisine_type]:
            if source:
                parts = [p.strip() for p in source.replace("，", ",").split(",") if p.strip()]
                tags.extend(parts)
        
        shop_dict['attributes_tags'] = list(dict.fromkeys(tags))
        shop_dict['merchant_category'] = shop.attributes.merchant_category

        # 設施排序與過濾
        raw_vdb = self._parse_json(shop.attributes.facility_tags)
        raw_list = raw_vdb if isinstance(raw_vdb, list) else []
        shop_dict['facility_tags'] = [f for f in self.FACILITY_ORDER if f in raw_list]

        logger.debug(f"[ShopService] 標籤處理完成 | 屬性標籤: {len(shop_dict['attributes_tags'])} | 設施標籤: {len(shop_dict['facility_tags'])}")