import os
import logging
from dotenv import load_dotenv

load_dotenv()

# 取得目前 services.py 所在的資料夾路徑，並指向上一層的 photos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTOS_DIR = os.path.normpath(os.path.join(BASE_DIR,"..", "photos"))
IMAGES_BASE_URL = os.getenv("IMAGES_BASE_URL", "http://localhost:5003/images/")

def add_photos_to_shop(shop_data: dict):
    """
    針對單一店家的 dict 補上照片列表邏輯
    """
    store_id_str = str(shop_data['id']).zfill(3)
    photo_list = []
    
    for i in range(1, 11):
        photo_name = f"{store_id_str}{str(i).zfill(2)}.jpg"
        
        # 檢查實體檔案是否存在
        if os.path.exists(os.path.join(PHOTOS_DIR, photo_name)):
            full_url = f"{IMAGES_BASE_URL}{photo_name}"
            photo_list.append(full_url)
    
    shop_data['photos'] = photo_list
    return shop_data