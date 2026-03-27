import os
import json
from app.logger import logger
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.utils.database_conn import get_db
from app.models.models import Restaurant
from dotenv import load_dotenv
from app.service.shop_service import ShopService

load_dotenv()
shop_router = APIRouter()

IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://192.168.1.112:5003/images/")
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

@shop_router.get("/get_place_info/{pid}")
async def get_shop_info(
    pid: int, 
    sid: str, 
    db: Session = Depends(get_db)
):
    logger.info(f"[GET Request] SID: {sid} | PID: {pid}")
    
    # 透過 Service 獲取乾淨的資料
    service = ShopService(db)
    shop_data = service.get_shop_info(pid)
    
    if not shop_data:
        logger.error(f"Shop not found: PID {pid} by SID {sid}")
        raise HTTPException(status_code=404, detail="Shop not found")
    
    return {
        "status": "success",
        "sid": sid, 
        "data": shop_data
    }