import os
import json
from logger import logger
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import Restaurant
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost:5003/images/")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTOS_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "photos"))

def add_photos_to_shop(shop_data: dict):
    store_id_str = str(shop_data['id']).zfill(3)
    photo_list = []
    for i in range(1, 11):
        photo_name = f"{store_id_str}{str(i).zfill(2)}.jpg"
        if os.path.exists(os.path.join(PHOTOS_DIR, photo_name)):
            photo_list.append(f"{IMAGES_BASE_URL}{photo_name}")
    shop_data['photos'] = photo_list
    return shop_data

@router.get("/get_place_info/{pid}")
async def get_shop_info(
    pid: int, 
    sid: str,  # FastAPI 會自動從 URL 的 ?sid=... 抓取
    db: Session = Depends(get_db)
):
    # 日誌輸出
    logger.info(f"[GET Request] SID: {sid} | PID: {pid}")
    # 店家查詢
    shop = db.query(Restaurant).options(joinedload(Restaurant.attributes)).filter(Restaurant.id == pid).first()
    
    if not shop:
        logger.error(f"Shop not found: PID {pid} by SID {sid}")
        raise HTTPException(status_code=404, detail="Shop not found")
    
    # 轉換字典邏輯
    shop_dict = {c.name: getattr(shop, c.name) for c in shop.__table__.columns}
    # 處理opening_hours字串問題
    if shop_dict.get('opening_hours'):
        try:
            # 將字串轉為 Python 字典
            shop_dict['opening_hours'] = json.loads(shop_dict['opening_hours'])
        except (json.JSONDecodeError, TypeError):
            # 如果格式不對或原本就是空值，保持原樣或給空字典
            shop_dict['opening_hours'] = {}

    # 提取 PlaceAttribute 的欄位
    # 因為 uselist=False，shop.attributes 是一個單一物件或 None
    if shop.attributes:
        shop_dict['food_type'] = shop.attributes.food_type
        shop_dict['cuisine_type'] = shop.attributes.cuisine_type
        shop_dict['merchant_categories'] = shop.attributes.merchant_categories
        shop_dict['has_dine_in'] = shop.attributes.has_dine_in
        shop_dict['has_takeout'] = shop.attributes.has_takeout
    else:
        # 如果該店沒有屬性資料，給予預設值
        shop_dict['food_type'] = None
        shop_dict['cuisine_type'] = None
        shop_dict['merchant_categories'] = None
        shop_dict['has_dine_in'] = False
        shop_dict['has_takeout'] = False

    # 補上照片 (從 services 引入的共用邏輯)
    shop_dict = add_photos_to_shop(shop_dict)

    # 回傳 JSON 包含 sid，這是防止前端 Race Condition 的關鍵關鍵！
    return {
        "status": "success",
        "sid": sid, 
        "data": shop_dict
    }