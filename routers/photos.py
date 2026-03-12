import os
from logger import logger
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
# 這裡要從你的服務層引入統一的路徑定義
from services.photo_helper import PHOTOS_DIR 

router = APIRouter()

@router.get("/images/{filename:path}")
async def get_photo(filename: str):
    try:
        # 使用服務層定義好的 PHOTOS_DIR，避免路徑層級算錯
        file_path = os.path.normpath(os.path.join(PHOTOS_DIR, filename))

        # 安全性檢查：防止目錄穿越 (Directory Traversal)
        if not file_path.startswith(PHOTOS_DIR):
            logger.error(f"Security Alert: Attempted directory traversal -> {file_path}")
            raise HTTPException(status_code=400, detail="Invalid filename")

        # 檢查檔案是否存在
        if not os.path.exists(file_path):
            logger.warning(f"File not found: {file_path}")
            raise HTTPException(status_code=404, detail="File not found")

        logger.info(f"Serving file: {file_path}")
        return FileResponse(file_path)

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Internal Server Error in Photo API: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")