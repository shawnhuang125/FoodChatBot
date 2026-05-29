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
    └── v1/ (或 v2, v3 等版本目錄)
        ├── task1/
        │   ├── final_lora_adapter/ (內含 adapter_config.json 等檔案)
        │   └── checkpoint-XXXX/ (微調過程中的檢查點)
        ├── task2/
        │   ├── final_lora_adapter/
        │   └── checkpoint-XXXX/
        └── task3/
            ├── final_lora_adapter/
            └── checkpoint-XXXX/
```

### 4. 環境變數設定
在專案根目錄建立 `.env` 檔案，複製並填入以下配置：

```env
# =====================================================================
# 🌐 1. 伺服器與非同步佇列配置 (Server & Queue)
# =====================================================================
API_SERVER_HOST=0.0.0.0            # API 伺服器監聽位址
API_SERVER_PORT=5000            # API 伺服器連接埠
MAX_CONCURRENT=2                # 系統允許的最大並行推論請求數
MAX_QUEUE_SIZE=1                # 推論佇列的最大等待長度
API_TIMEOUT=25.0                # API 請求超時設定（秒）
HTTPX_MAX_CONNECTIONS=100       # HTTP 請求最大連線數
HTTPX_MAX_KEEPALIVE=20          # HTTP 保持活躍連線數

# =====================================================================
# 🔗 2. 外部上游 API 串接網址 (External APIs)
# =====================================================================
NEW_SEARCH_API_URL=http://192.168.1.113:5000/search_result
PAGE_SEARCH_API_URL=http://192.168.1.118:5004/place_search/page

# =====================================================================
# 🤖 3. 線上推論模型路徑配置 (Models Configuration)
# =====================================================================
BASE_MODEL_NAME=Qwen/Qwen2.5-7B-Instruct
# ⚠️ 修正重點：將線上讀取目錄與微調輸出目錄全面對齊至最新 v6 版本，防範讀錯版本
MODELS_BASE_DIR=/app/models/qwen2.5-7b/v6
TASK1_ADAPTER_DIR=task1/checkpoint-1000
TASK2_ADAPTER_DIR=task2/final_lora_adapter
TASK3_ADAPTER_DIR=task3/final_lora_adapter

# =====================================================================
# ⚙️ 4. 多任務模型線上推論參數 (Inference Parameters)
# =====================================================================
TASK1_MAX_TOKENS=256            # Task 1 解析器的最大生成長度
TASK1_REP_PENALTY=1.0           # Task 1 重複處罰係數

TASK2_MAX_TOKENS=512            # Task 2 補問助理的最大生成長度
TASK2_TEMP=0.7                  # Task 2 溫度係數（控制創造力）
TASK2_TOP_P=0.9                 # Task 2 核採樣參數
TASK2_REP_PENALTY=1.1           # Task 2 重複處罰係數

TASK3_MAX_TOKENS=1024           # Task 3 推坑達人的最大生成長度
TASK3_TEMP=0.3                  # Task 3 溫度係數
TASK3_TOP_P=0.8                 # Task 3 核採樣參數
TASK3_REP_PENALTY=1.0           # Task 3 重複處罰係數

# =====================================================================
# 🧠 5. 對話記憶體與系統日誌 (Memory & Logging)
# =====================================================================
MEMORY_MAX_TURNS=3              # 每個使用者對話保留的最大輪次（Context Window）
LOG_FILE_PATH=app.log           # 系統日誌儲存路徑
LOG_LEVEL=INFO                  # 日誌層級 (DEBUG/INFO/WARNING/ERROR)

# =====================================================================
# 🏋️ 6. 基礎微調全局參數備援 (Fine-tuning Global Defaults)
# =====================================================================
FT_BASE_MODEL_NAME=Qwen/Qwen2.5-7B-Instruct
FT_DATASET_DIR=dataset
FT_MODELS_DIR=models/qwen2.5-7b/v6
FT_MODEL_MAX_LENGTH=2048
FT_TARGET_MODULES=q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj
FT_OPTIM=paged_adamw_32bit

# ⚡【矩陣並行優化】：8-bit 鋼鐵對齊 float16 提速方案
FT_BATCH_SIZE=2       
FT_GRAD_ACCUM_STEPS=8
FT_LOGGING_STEPS=10
FT_SAVE_STEPS=200

# =====================================================================
# 🎯 各任務微調超參數精準分流區 (Task-specific overrides)
# =====================================================================

# --- 🧪 TASK 1: 餐廳語意解析器 (Strict JSON Mode) ---
FT_TASK1_DATASET=train_task1_shuffled.json
FT_TASK1_OUTPUT_DIR=task1
FT_TASK1_EPOCHS=4              # 🎯 收斂點快，4 輪可達到黃金精準度
FT_TASK1_LEARNING_RATE=1e-5    # 🎯 溫和學習速率，防止破壞預訓練權重
FT_TASK1_LORA_R=32             # LoRA Rank
FT_TASK1_LORA_ALPHA=64
FT_TASK1_LORA_DROPOUT=0.01     # 極低 Dropout，逼模型死記 JSON 格式
FT_TASK1_SAVE_STEPS=200

# --- 🗣️ TASK 2: 多輪補問助理 (Natural Chatting Mode) ---
FT_TASK2_DATASET=train_task2_shuffled.json
FT_TASK2_OUTPUT_DIR=task2
FT_TASK2_EPOCHS=2              # 防止過度擬合（Overfitting）日常對話
FT_TASK2_LEARNING_RATE=2e-5    # 降溫學習速率
FT_TASK2_LORA_R=16             # 極窄通道
FT_TASK2_LORA_ALPHA=32
FT_TASK2_LORA_DROPOUT=0.15     # 提高雜訊率，增加對話靈活性
FT_TASK2_SAVE_STEPS=50         # 密集的存檔點以供挑選精華版本

# --- 🍳 TASK 3: 美食推坑達人 (Data-Grounded NLG Mode) ---
FT_TASK3_DATASET=train_task3_shuffled.json
FT_TASK3_OUTPUT_DIR=task3
FT_TASK3_EPOCHS=2              # 防止腦補
FT_TASK3_LEARNING_RATE=2e-5
FT_TASK3_LORA_R=16
FT_TASK3_LORA_ALPHA=32
FT_TASK3_LORA_DROPOUT=0.1      # 中高雜訊防禦
FT_TASK3_SAVE_STEPS=200
FT_TASK3_BATCH_SIZE=1          # 單筆輸入，極限壓低顯存消耗
FT_TASK3_GRAD_ACCUM_STEPS=16   # 維持相同的 Effective Batch Size

# =====================================================================
# 🎲 7. 資料集生成種子與測試網頁配置 (Generator & GUI)
# =====================================================================
FT_GENERATOR_OUTPUT_FILE=dataset/auto_dataset.json
FT_SHUFFLE_SEED=42              # 資料集洗牌種子
FT_TEST_SEED=91                 # 測試隨機種子

GUI_DEFAULT_SID=test_user_001   # 預設測試 ID
GUI_DEFAULT_LAT=23.001600       # 預設測試緯度
GUI_DEFAULT_LNG=120.252800      # 預設測試經度
GUI_API_SERVER_HOST=0.0.0.0
GUI_API_PORT=5000               # GUI 調用的 API 端口
GUI_API_TIMEOUT=60.0            # 推論請求超時限制
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