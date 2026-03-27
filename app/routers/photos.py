from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.utils.database_conn import get_db
from app.service.shop_service import ShopService
from app.logger import logger

photo_router = APIRouter()

@photo_router.get("/get_place_info/{pid}")
async def get_shop_info(
    pid: int, 
    sid: str, 
    db: Session = Depends(get_db)
):
    logger.info(f"[GET Request] SID: {sid} | PID: {pid}")
    
    # 透過 OOP Service 處理所有煩人的邏輯
    shop_data = ShopService(db).get_shop_info(pid)
    
    if not shop_data:
        logger.error(f"Shop not found: PID {pid} by SID {sid}")
        raise HTTPException(status_code=404, detail="Shop not found")
    
    return {
        "status": "success",
        "sid": sid, 
        "data": shop_data
    }