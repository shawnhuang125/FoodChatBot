# ./app/routes/__init__.py
from fastapi import APIRouter
from app.routers.business import shop_router
from app.routers.photos import photo_router
# 建立總路由
api_router = APIRouter()

# 這裡可以統一加上 prefix 或 tags，方便管理
api_router.include_router(photo_router, tags=["Photos"])
api_router.include_router(shop_router, tags=["Business"])

# 未來如果有新功能，直接在這裡一行 include 即可
# api_router.include_router(user.router, prefix="/user", tags=["User"])