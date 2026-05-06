import uvicorn
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # 必須引入這個
from app.routers import api_router 
from app.utils.database_conn import engine, Base
from dotenv import load_dotenv

load_dotenv() # 在最前面載入環境變數

# 初始化資料庫
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Business API Service")

# 為了取得 run.py 所在的根目錄，並指向 photos 資料夾
PHOTO_DIR = os.getenv("PHOTO_PATH", os.path.join(os.path.dirname(__file__), "photos"))

# 掛載靜態檔案
# app.mount("/images", StaticFiles(directory=PHOTO_DIR), name="images")


# 中間件配置
# 註冊總路由
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5003)