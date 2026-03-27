import os
import json
from typing import Optional, List
from app.logger import logger

class PhotoService:
    def __init__(self):
        # 1. 從環境變數讀取目錄路徑，若沒設定則使用預設相對路徑
        default_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../photos"))
        raw_dir = os.getenv("PHOTO_SYSTEM_DIR", default_path)
        
        # 確保轉成絕對路徑，避免後續 os.path.join 出錯或安全性檢查失效
        self.photos_dir = os.path.abspath(raw_dir)
        
        # 2. 從環境變數讀取圖片 Base URL
        self.images_base_url = os.getenv("IMAGES_BASE_URL", "http://localhost:5003/images/")

        # 啟動時檢查目錄是否存在
        if not os.path.exists(self.photos_dir):
            logger.error(f"Critical: Photo directory does not exist at {self.photos_dir}")

    def get_valid_image_path(self, filename: str) -> str:
        """
        獲取安全的圖片實體絕對路徑 (用於 FileResponse)
        """
        # 1. 組合並規範化路徑
        target_path = os.path.abspath(os.path.join(self.photos_dir, filename))

        # 2. 安全性檢查：防止目錄穿越 (Directory Traversal)
        if not target_path.startswith(self.photos_dir):
            logger.error(f"Security Alert: Directory traversal attempt -> {target_path}")
            return "SECURITY_ERROR"

        # 3. 檢查檔案是否存在
        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            logger.warning(f"File not found: {target_path}")
            return "NOT_FOUND"

        return target_path

    def get_shop_photos(self, shop_id: int) -> List[str]:
        """
        根據店家 ID 搜尋對應的實體檔案並回傳公開 URL 列表
        """
        store_id_str = str(shop_id).zfill(3)
        photo_list = []
        
        for i in range(1, 11):
            photo_name = f"{store_id_str}{str(i).zfill(2)}.jpg"
            file_path = os.path.join(self.photos_dir, photo_name)
            
            # 這裡直接檢查實體檔案是否存在
            if os.path.exists(file_path) and os.path.isfile(file_path):
                # 拼接成外部訪問的 URL
                photo_list.append(f"{self.images_base_url}{photo_name}")
                
        return photo_list