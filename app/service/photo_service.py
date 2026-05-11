# ./app/services/photo_services.py
import os
import json
from typing import Optional, List
from app.logger import logger
from app.config import Config

class PhotoService:
    def __init__(self):
        # 直接從 Config 讀取
        self.photos_dir = Config.PHOTO_PATH
        self.images_base_url = Config.IMAGES_BASE_URL

        logger.info(f"[PhotoService] 初始化完成 | 實體目錄: {self.photos_dir}")
        logger.info(f"[PhotoService] 初始化完成 | URL 前綴: {self.images_base_url}")

        if not os.path.exists(self.photos_dir):
            logger.error(f"Critical: Photo directory does not exist at {self.photos_dir}")

    def get_valid_image_path(self, filename: str) -> str:
        target_path = os.path.abspath(os.path.join(self.photos_dir, filename))
        
        # 安全性檢查
        if not target_path.startswith(os.path.abspath(self.photos_dir)):
            return "SECURITY_ERROR"
        if not os.path.exists(target_path):
            return "NOT_FOUND"
        return target_path

    def get_shop_photos(self, shop_id: int) -> List[str]:
        """
        根據店家 ID 搜尋對應的實體檔案並回傳公開 URL 列表
        規則：店家 ID (4位) + 序號 (2位) -> 例如 000501.jpg
        """
        # 1. 將 shop_id 補齊至 4 位數 (例如 5 -> "0005")
        store_id_str = str(shop_id).zfill(4)
        photo_list = []

        logger.info(f"[PhotoService] 開始搜尋店家 ID: {shop_id} (前綴: {store_id_str}) 的圖片...")
        
        # 2. 搜尋 01 到 10 的照片
        for i in range(1, 11):
            # 序號補齊至 2 位數
            photo_name = f"{store_id_str}{str(i).zfill(2)}.jpg"
            file_path = os.path.join(self.photos_dir, photo_name)
            
            # 檢查實體檔案是否存在
            if os.path.exists(file_path) and os.path.isfile(file_path):
                # 拼接成 URL (IMAGES_BASE_URL 後面通常已經帶有 /)
                final_url = f"{self.images_base_url}{photo_name}"
                photo_list.append(final_url)
                logger.debug(f"[PhotoService] 找到實體圖片: {file_path} -> URL: {final_url}")
        
        # 3. 總結搜尋結果
        if photo_list:
            logger.info(f"[PhotoService] 店家 ID: {shop_id} 搜尋完畢，共找到 {len(photo_list)} 張圖片。")
        else:
            logger.warning(f"[PhotoService] 店家 ID: {shop_id} 搜尋完畢，未找到任何圖片！")
            logger.warning(f"請檢查目錄 {self.photos_dir} 內是否有 {store_id_str}01.jpg 等檔案。")

        return photo_list