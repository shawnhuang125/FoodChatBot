import os
import json
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session, joinedload
from app.models.models import Restaurant
from app.service.photo_service import PhotoService  # 確保有引入
from app.logger import logger

class ShopService:
    # 設施排序與過濾定義
    FACILITY_ORDER = ["內用", "外帶", "冷氣", "吃到飽", "特約停車場"]

    def __init__(self, db: Session):
        self.db = db
        # 圖片邏輯委派給專業的 PhotoService 處理
        self.photo_service = PhotoService()

    def get_shop_info(self, pid: int) -> Optional[Dict[str, Any]]:
        shop = self._fetch_shop(pid)
        if not shop:
            return None

        # 這裡 getattr 已經把資料從資料庫 Column 轉成了真正的 Python 原生型別 (int/str)
        shop_dict = {c.name: getattr(shop, c.name) for c in shop.__table__.columns}
        
        # 1. 處理 JSON 欄位
        shop_dict['opening_hours'] = self._parse_json(shop_dict.get('opening_hours'))
        
        # 2. 處理標籤與屬性
        self._inject_attributes(shop, shop_dict)

        # 3. 呼叫 PhotoService 獲取圖片 URL 清單
        # 傳入 shop_dict['id'] (int)，完全避開 SQLAlchemy Column 型別問題
        shop_dict['photos'] = self.photo_service.get_shop_photos(shop_dict['id'])
        
        return shop_dict

    def _fetch_shop(self, pid: int):
        """私有方法：負責資料庫查詢"""
        return self.db.query(Restaurant)\
            .options(joinedload(Restaurant.attributes))\
            .filter(Restaurant.id == pid)\
            .first()

    # --- 💡 重點：原本這裡的 _resolve_photos 方法已經被移除，因為邏輯已移至 PhotoService ---

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