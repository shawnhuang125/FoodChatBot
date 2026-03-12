import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import photos, business
from database import engine, Base

# 初始化資料庫
Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊模組
app.include_router(photos.router)
app.include_router(business.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5003)