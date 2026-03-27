import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import api_router  # 引入剛才定義好的總路由
from app.utils.database_conn import engine, Base

# 初始化資料庫
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Business API Service")

# 中間件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊總路由：一行搞定所有模組
app.include_router(api_router)

if __name__ == "__main__":
    # 建議 port 也可以從 .env 讀取
    uvicorn.run(app, host="0.0.0.0", port=5003)