# app/routes/__init__.py
"""
Controller 層匯入中心
此處僅定義 API 入口點，負責請求調度 (Dispatching) 與回應格式封裝。
嚴禁在此處撰寫重型業務邏輯，邏輯應封裝於 Service 層，資料運算應封裝於 Repository 層。

優點：
1. 分層明確，方便單元測試。
2. 保持 main.py 簡潔。
3. 避免模組循環引用。
"""
from fastapi import APIRouter
from .hybird_search_routes import place_search


# 建立一個總路由
api_router = APIRouter()

# 註冊所有子路由
# 未來如果有新的路由，直接在這裡增加一行即可
api_router.include_router(place_search, tags=["Search"])

__all__ = ["api_router"]