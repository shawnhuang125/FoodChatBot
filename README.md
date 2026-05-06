# 🚀 AI Streaming Gateway (四層模組化架構)

這是一個專為高併發 AI 聊天與串流回應（Streaming）設計的 API 網關。基於 **FastAPI** 與 **Socket.IO** 構建，並整合 **Redis** 進行分散式狀態管理與頻率限制。此專案已完全容器化，可透過 Docker Compose 實現一鍵部署。

## ✨ 核心特色與架構介紹

本系統採用**四層模組化架構**設計，確保高內聚與低耦合：

1. **🌐 對外通訊與路由層 (API & Events)**
   - 透過 `FastAPI` 處理標準 HTTP 請求（如狀態查詢、強制清理、檢索中繼）。
   - 透過 `python-socketio` (ASGI) 處理全雙工的 WebSocket 連線，維持與客戶端的長連線。
2. **🛡️ 狀態管理與安全監控層 (Security & State)**
   - **IP 限流機制**：利用 Redis 實現 2 秒內限連線一次的防刷機制。
   - **會話管理與心跳機制**：追蹤 `active_sids`，確保連線有效性。
   - **背景自癒巡檢**：定期執行 `monitor_loop`，自動回收超過 10 分鐘無回應的「殭屍連線」與「幽靈 SID」，釋放記憶體。
3. **🧠 核心處理與封裝組件 (Core Processing)**
   - **非同步串流轉發引擎**：使用 `httpx` 的非同步連線池，將使用者的輸入轉發至遠端 AI 伺服器，並透過 `aiter_text()` 接收打字機（Streaming）效果。
   - **JSON 容錯解析**：內建防呆機制，能妥善處理 AI 伺服器回傳的不完整或非標準 JSON 格式。
4. **🧱 底層儲存與外部通訊 (Storage & Clients)**
   - 整合 `redis.asyncio` 進行極速的 Key-Value 存取。
   - 使用生命週期管理器 (`lifespan`) 妥善初始化與關閉 Redis / HTTPX 連線池資源。

## 🛠️ 技術堆疊

* **Backend Framework**: Python 3.10, FastAPI, Uvicorn (搭載 uvloop)
* **WebSocket**: python-socketio
* **Async HTTP Client**: HTTPX
* **In-Memory DB**: Redis
* **Containerization**: Docker, Docker Compose

## 📂 專案目錄結構

```text
.
├── main.py                # 應用程式主進入點（四層架構程式碼）
├── requirements.txt       # Python 依賴套件清單
├── Dockerfile             # Docker 映像檔建置藍圖
├── docker-compose.yml     # 多容器部署配置檔
└── .env                   # 環境變數設定檔（需自行建立）