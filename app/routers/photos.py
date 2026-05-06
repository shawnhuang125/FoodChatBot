# ./app/routers/photos.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.service.photo_service import PhotoService # 確保引入路徑正確
from app.logger import logger

photo_router = APIRouter()
photo_service = PhotoService()

@photo_router.get("/images/{filename}")
async def get_image(filename: str):
    """
    自訂的圖片讀取路由：
    接收如 http://192.168.1.112:5003/images/17601.jpg 的請求
    """
    logger.info(f"[Photo Router] 收到圖片讀取請求: {filename}")
    
    # 透過 PhotoService 驗證檔名並取得安全的絕對路徑
    file_path = photo_service.get_valid_image_path(filename)
    
    # 根據 Service 回傳的狀態進行錯誤處理
    if file_path == "SECURITY_ERROR":
        raise HTTPException(status_code=403, detail="拒絕存取：不合法的路徑請求")
    elif file_path == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="找不到圖片檔案")
        
    # 一切正常，回傳實體圖片檔案給前端
    return FileResponse(path=file_path, media_type="image/jpeg")