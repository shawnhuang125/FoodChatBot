# 🎓 崑山科大 AI 美食推薦機器人：自動化部署指南

本專案將美食推薦 AI 系統（基於 **Qwen 2.5-7B-Instruct**）進行容器化部署，並導入 **Multi-LoRA 三核心架構**。透過 Docker 虛擬化技術，實現雙顯卡（RTX 4060 Ti x2）負載平衡與 8-bit 量化推論，提供穩定且快速的 API 服務。

---

## ✨ 特色功能

* **🧠 大腦分離架構**：使用 Hugging Face 快取掛載基礎模型 (15GB)，免除 Docker 重啟時重複下載的耗時。
* **🛠️ 多任務微調 (Multi-LoRA)**：同時掛載 Task 1、Task 2、Task 3 專屬附屬大腦，支援動態切換推論模式。
* **⚡ 硬體最佳化**：啟用 8-bit 量化 (`bitsandbytes`) 與 `device_map="auto"`，完美適配雙卡顯存負載平衡。
* **🐳 一鍵啟動**：透過 Docker Compose 封裝所有依賴環境、CUDA 驅動對接與 FastAPI (Uvicorn) 伺服器。

---

## 🛠️ 環境需求

* **作業系統**: Windows 10/11 (需安裝 Docker Desktop 並啟用 WSL 2 Backend)
* **硬體規格**: NVIDIA RTX 40 系列 (建議 16GB 以上總顯存，支援雙卡並行)
* **驅動程式**: NVIDIA Driver 550.xx 以上 (支援 CUDA 12.4+)
* **必備工具**: Git, Python 3.10+, Docker Desktop

---

## 🚀 快速開始

### 1. 取得專案原始碼
```bash
git clone git clone -b feature/minfuchen-chat-logic [https://github.com/shawnhuang125/FoodChatBot.git](https://github.com/shawnhuang125/FoodChatBot.git)
cd FoodChatBot
cd "Capstone Project"
```

### 2. 預下載基礎模型
為了節省部署時間，請先在 **Windows 本機** 下載模型快取：

```bash
pip install huggingface_hub
```

在 Python 環境中執行：
```python
from huggingface_hub import snapshot_download

# 下載 Qwen 基礎模型
snapshot_download(repo_id="Qwen/Qwen2.5-7B-Instruct")
# 模型預設會儲存於 C:\Users\<你的用戶名>\.cache\huggingface
```

### 3. 配置微調權重 (LoRA Adapters)
請確保微調權重依照以下目錄結構放置，否則容器將無法識別：

```plaintext
models/
└── qwen2.5-7b/
    ├── task1/
    │   └── final_lora_adapter/ (內含 adapter_config.json 等檔案)
    ├── task2/
    │   └── final_lora_adapter/
    └── task3/
        └── final_lora_adapter/
```

### 4. 環境變數設定
在專案根目錄建立 `.env` 檔案，複製並填入以下配置：

```env
# Server & Queue
MAX_CONCURRENT=2
MAX_QUEUE_SIZE=3

# External APIs
NEW_SEARCH_API_URL=http://192.168.1.113:5000/search_result
PAGE_SEARCH_API_URL=http://192.168.1.118:5004/place_search/page

# Models Configuration
# 基礎模型：維持名稱即可，它會去快取目錄找
BASE_MODEL_NAME=Qwen/Qwen2.5-7B-Instruct
# 微調模型：指向你掛載進去的 /app/models
MODELS_BASE_DIR=/app/models/qwen2.5-7b

# Memory Management
MEMORY_MAX_TURNS=3

# Logging
LOG_FILE_PATH=app.log
```

### 5. 修改 Docker 掛載路徑
打開 `docker-compose.yml`，將 `<你的用戶名>` 替換為實際 Windows 帳號名稱：

```yaml
    volumes:
      # 基礎模型快取傳送門 (本機與容器共享)
      - "C:/Users/<你的用戶名>/.cache/huggingface:/root/.cache/huggingface"
      # 微調模型對接
      - ./models:/app/models
      # 記錄檔對接
      - ./app.log:/app/app.log
```

### 6. 一鍵編譯與啟動
確保 Docker 已啟動後，執行以下指令：

```bash
docker-compose up --build -d
```

---

## 🚦 驗證與測試

### 🔍 監控開機日誌
輸入指令查看大腦載入進度（約需 60~120 秒）：

```bash
docker-compose logs -f
```

> 當出現 `✅ 三核心大腦載入完成，推論引擎啟動！` 以及 `INFO: Uvicorn running on http://0.0.0.0:5000` 即代表啟動成功。

### 🌐 API 測試
開啟瀏覽器訪問 **Swagger UI** 進行推論測試：
👉 [http://localhost:5000/docs](http://localhost:5000/docs)

### 🚀 硬體狀態監控
於終端機輸入以下指令，確認雙顯卡記憶體皆已正確分配：

```bash
nvidia-smi
```

---
**Engineer Note**: 
本專案專為雙卡環境優化，若使用單卡請調整 `device_map` 參數以免顯存溢出。