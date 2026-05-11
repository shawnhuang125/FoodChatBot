import os
from dotenv import load_dotenv

# 加載 .env
load_dotenv()

class Config:
    # 1. 先讀取原始值
    _raw_photo_path = os.getenv("PHOTO_PATH")

    # 2. 處理路徑：確保它絕對不是 None
    if _raw_photo_path:
        # 如果有讀到，轉為規範化的路徑
        PHOTO_PATH = os.path.normpath(_raw_photo_path)
    else:
        # 如果沒讀到，給一個預設路徑 (例如專案根目錄下的 photos)
        # 這樣 PHOTO_PATH 的型別就百分之百是 str，紅線就會消失
        PHOTO_PATH = os.path.join(os.getcwd(), "photos")

    # 圖片 URL
    IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost:5003/images/")

    @classmethod
    def validate_config(cls):
        """
        在啟動時驗證。
        現在 cls.PHOTO_PATH 確定是 str，os.path.exists 就不會報錯。
        """
        if not os.path.exists(cls.PHOTO_PATH):
            # 這裡可以選擇自動建立目錄，更人性化
            try:
                os.makedirs(cls.PHOTO_PATH)
                print(f"[Config] 已自動建立圖片目錄: {cls.PHOTO_PATH}")
            except Exception as e:
                print(f"[Config] 警告：目錄不存在且無法建立: {cls.PHOTO_PATH}, Error: {e}")

# (選用) 在 Config 定義完後直接跑一次驗證
Config.validate_config()