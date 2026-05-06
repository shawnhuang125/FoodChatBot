# run.py

import logging
import os
import uvicorn
from app.__init__ import app  # 確保你將 create_app 產出的 app 實例放在 app/main.py
from app.config import Config

# Initialize Logging (保持不變)
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logging.info("Logger initialized (run.py - FastAPI mode).")

# 資料庫連線資訊 log (保持不變)
logging.info(f"Database: MySQL. Host: {Config.DB_HOST}, Database: {Config.DB_NAME}")
logging.info(f"Database: Qdrant. Host: {Config.VECTOR_DB_HOST}")
logging.info(f"Connect to Photo Service Successfully. URL:{Config.IMAGES_URL}")

if __name__ == "__main__":
    logging.info("Starting FastAPI server via Uvicorn...")
    
    # 使用 uvicorn 啟動，取代原本的 app.run
    # host: 監聽地址
    # port: 埠號 (你原本設定 5004)
    # reload: 等同於 Flask 的 debug=True (僅建議開發環境使用)
    uvicorn.run("run:app", host="0.0.0.0", port=5004, reload=False,log_level="info")