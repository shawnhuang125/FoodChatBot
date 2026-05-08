# 🚀 FoodChatBot - 核心 API 網關 (API Gateway)

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Socket.io](https://img.shields.io/badge/Socket.io-010101?style=for-the-badge&logo=socket.io)
![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)
![Redis](https://img.shields.io/badge/redis-%23DD0031.svg?style=for-the-badge&logo=redis&logoColor=white)

這是 **FoodChatBot** 專案的核心通訊中心，基於 **FastAPI** 與 **Socket.IO** 打造。負責處理前端 App 的即時通訊請求、進行 IP 限流與連線狀態管理，並透過 HTTP 連線池高效轉發請求至後端 AI 處理伺服器。

---

## ✨ 核心優勢與架構

* **單進程非同步架構 (Single-Worker Async)**：徹底解決 Socket.IO 在分散式環境下握手階段的 `Invalid session` 問題，確保 WebSocket 連線極度穩定。
* **Redis 分散式狀態管理**：內建連線心跳偵測 (Heartbeat)、殭屍連線自動回收與自癒機制。
* **防刷限流機制**：具備 IP 頻率限制（2 秒內限連線 1 次），有效保護後端 AI 資源不被惡意消耗。
* **Docker 容器化部署**：一鍵啟動，環境統一，確保「開發、測試、生產」環境一致。

---

## 🛠️ 開發環境需求

在開始之前，請確保你的電腦或伺服器已安裝以下軟體：
1. **Git**: 用於版本控制與代碼下載。
2. **Docker & Docker Compose**: 用於執行容器化服務（請確保服務已啟動）。
3. **VS Code**: 推薦使用的程式碼編輯器。

---

## 🚀 快速啟動步驟 (Step-by-Step)

### 1. 下載專案與切換分支
打開終端機，執行以下指令：
```bash
# 複製遠端專案
git clone [https://github.com/shawnhuang125/FoodChatBot.git](https://github.com/shawnhuang125/FoodChatBot.git)

# 進入專案資料夾
cd FoodChatBot

# 切換到 API 開發專屬分支
git checkout feature/fuminwu-api
```

### 2. 配置環境變數 (.env)
在專案根目錄下（與 `docker-compose.yml` 同一層）手動新增一個 `.env` 檔案，並填入以下內容：
```env
# ====== 網關監聽設定 ======
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=5000

# ====== Redis 暫存資料庫連線 ======
REDIS_URL=redis://redis:6379/0

# ====== 後端 AI 微服務位置 (請依實際區網 IP 更改) ======
TEXT_BOT_API_URL=[http://192.168.1.116:5000/text_bot_input](http://192.168.1.116:5000/text_bot_input)
TEXT_BOT_API_URL_1=[http://192.168.1.116:5000/free_memory](http://192.168.1.116:5000/free_memory)
PLACE_SEARCH_URL=[http://192.168.1.118:5004/place_search](http://192.168.1.118:5004/place_search)
```

### 3. 一鍵啟動服務
```bash
# 自動構建鏡像並於背景啟動
docker compose up -d --build
```

### 4. 檢查運作狀態
```bash
# 持續追蹤 API 網關日誌
docker logs -f streaming-gateway
```
💡 **成功指標**：看見 `🚀 API Gateway [單進程終極穩定版]` 且無紅色報錯即可（按 `Ctrl+C` 退出追蹤）。

---

## 🔌 API 服務端點 (Endpoints)

| 類型 | 端點位置 | 說明 |
| :--- | :--- | :--- |
| **API 後台** | `http://localhost:5000/docs` | 視覺化 Swagger UI 測試介面 |
| **健康檢查** | `GET http://localhost:5000/status` | 查看連線狀態與當前在線人數 |
| **即時通訊** | `ws://localhost:5000` | 前端 Socket.IO 連線通道 |

> **⚠️ 前端連線提示：**
> 前端 App 連線時應設定 `transports: ['websocket']` 以強制使用 WebSocket 長連線，跳過 HTTP 輪詢，提升效能。

---

## 📊 運行監控與除錯 (Monitoring & Debugging)

服務部署上線後，可透過以下指令進行即時監控與效能排錯：

### 1. 系統資源監控 (CPU/Memory)
查看容器當前的 CPU 與記憶體消耗狀態：
```bash
# 即時顯示所有容器的資源佔用率
docker stats

# 僅顯示 gateway 容器的資源佔用
docker stats streaming-gateway
```

### 2. API 網關日誌進階操作
當遇到問題時，精準查看 Log 是除錯的關鍵：
```bash
# 查看最後 100 行日誌並持續追蹤
docker logs --tail 100 -f streaming-gateway

# 搜尋日誌中特定關鍵字 (例如 Error)
docker logs streaming-gateway 2>&1 | grep "Error"
```

### 3. Redis 連線與狀態監控
網關的狀態高度依賴 Redis，可以透過內建 CLI 進行排查：
```bash
# 查看 Redis 當前連線客戶端數量與狀態
docker exec -it redis redis-cli info clients

# 進入 Redis 監聽模式 (即時查看所有讀寫指令，注意：會消耗較多效能)
docker exec -it redis redis-cli monitor

# 清除所有 Redis 快取 (⚠️ 警告：會踢除所有用戶連線狀態)
docker exec -it redis redis-cli flushall
```

---

## 🛑 管理與維護指令

```bash
# 停止並移除目前的容器
docker compose down

# 重新打包並啟動 (若有修改程式碼必執行)
docker compose up -d --build

# 清理系統中未使用的 Docker 映像檔與網路 (釋放硬碟空間)
docker system prune -f
```

---

## 👨‍💻 開發者資訊

* **專案負責人：** 吳富民 (Wu Fu-min)
* **學號：** 4120E007
* **系所：** 崑山科技大學 資工系 3A
* **版本：** v2.0.0 (單進程穩定版)
* **開發分支：** `feature/fuminwu-api`
