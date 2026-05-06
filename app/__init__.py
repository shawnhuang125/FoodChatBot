# ./app/__init__.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.utils.db import get_async_db_pool, close_all_connections
from app.routes import api_router
from app.utils.app_logger import app_log_manager, logger

app_log_manager.setup_logging()

# --- FastAPI 初始化 ---
app = FastAPI(title="Place Search Service", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# --- FastAPI 事件管理 ---

@app.on_event("startup")
async def startup_event():
    """
    FastAPI 服務啟動事件。

    設計動機（為什麼要在 startup 預熱？）
    ─────────────────────────────────────
    • 冷啟動問題：VectorService 內的 BGE-M3 嵌入模型首次載入約需 1.7 秒。
      若放在每次請求中初始化，第一位用戶每次都會等待這段延遲，嚴重影響 UX。
    • 共用單例：透過 app.state 將重型物件以「單例」形式掛載，
      所有請求皆共用同一份實例，避免記憶體重複占用。
    • 啟動順序設計：先建立 DB 連線池 → 再建立 Redis Cache → 最後載入 AI 模型，
      確保下游依賴的基礎設施（DB、快取）一定先於業務層就緒。
    """
    logger.info("FastAPI service is starting (Pre-warming services)...")

    # ── Step 1：初始化資料庫連線池 ──────────────────────────────────────────
    # 為什麼先建 DB 連線池：
    # HybridSQLBuilder 與 RdbmsRepository 在執行查詢時需要從池中借用連線。
    # 若連線池尚未準備好，第一個進來的請求就會觸發初始化，造成不可預期的延遲或競態條件。
    await get_async_db_pool()
    logger.info("[DB] 資料庫連線池已就緒。")

    # ── Step 2：初始化 Redis Session Cache ──────────────────────────────────
    # 為什麼先於 AI 模型建立 Cache：
    # SearchSessionCache 負責跨請求儲存分頁結果（TTL 短暫的 Redis Key）。
    # 若 AI 模型先於 Cache 就緒，而 startup 中途失敗，
    # 則 Redis 連線從未被驗證，首次翻頁請求才會爆出連線錯誤，難以診斷。
    # 提前建立可在服務啟動階段就發現 Redis 連線問題，做到「快速失敗（Fail Fast）」。
    try:
        from app.utils.search_session_cache import SearchSessionCache

        # 將 Cache 實例掛載到 app.state，讓所有路由都能透過 request.app.state.session_cache 取用
        app.state.session_cache = SearchSessionCache()
        logger.info("[Cache] Redis Session Cache 已就緒。")

        # ── Step 3：載入 AI 模型與業務層 Service ────────────────────────────
        # 為什麼放在最後：
        # AI 模型（BGE-M3）是最耗時的初始化步驟（約 1.7 秒）。
        # 讓它在 DB 與 Cache 確認就緒後才開始載入。
        # 能確保整條服務鏈路（DB→Cache→AI）依序驗證，任何一環失敗都能在啟動日誌中清楚定位。
        from app.services.vector_service import VectorService
        from app.services.hybrid_SQL_builder_service_v2 import HybridSQLBuilder
        from app.repository.rdbms_repository import RdbmsRepository

        # VectorService()：內部會載入 BGE-M3 嵌入模型，首次執行約 1.7 秒
        # 掛載到 app.state 後，後續所有請求共用此實例，不再重複付出載入代價
        app.state.vector_service = VectorService()

        # HybridSQLBuilder：解析 AI 傳入的 JSON intent，動態組裝 SQL 語句
        app.state.builder = HybridSQLBuilder()

        # RdbmsRepository：封裝 MySQL 非同步查詢邏輯；use_mock=False 代表連接真實資料庫
        app.state.rdbms_repo = RdbmsRepository(use_mock=False)

        logger.info("[AI] BGE-M3 模型與所有 Service 預熱完成。")

    except Exception as e:
        # 記錄詳細錯誤但不讓服務崩潰；
        # 若模型載入失敗，後續請求進到路由時會因 app.state 缺失屬性而拋出 AttributeError，
        # 屆時 500 回應可提示開發者查看此段啟動日誌
        logger.error(f"[Startup] 服務預熱失敗，請確認 Redis / DB / 模型檔案是否就緒: {e}")

    logger.info("FastAPI service started successfully.")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI service is shutting down...")
    
    # 1. 先關閉資料庫連線池
    try:
        await close_all_connections()
        logger.info("[DB] 資料庫連線池已安全釋放。")
    except Exception as e:
        logger.error(f"[DB] 關閉連線池時發生錯誤: {e}")

    # 2. 最後才關閉日誌監聽器 (確保最後的日誌有被寫入)
    app_log_manager.stop_logging()