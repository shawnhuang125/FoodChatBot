# AI Hybrid Search API (RAG Backend)
- 這是一個專為 AI 搜尋場景設計的後端系統。它採用 Hybrid Search (混合搜尋) 架構，能夠接收來自 LLM (Large Language Model) 解析後的 JSON 意圖，動態生成 -SQL 查詢語句，並結合向量資料庫 (Vector DB) 的語意搜尋結果，實現RAG (Retrieval-Augmented Generation) 檢索的功能。
- **主流程**
- `解析LLM生成之邏輯樹與查詢相關參數`-->`SQL地理預過濾`-->`時間過濾`-->`相似度需求檢索`-->`混和精排演篹法`-->`店家資料統一美觀處理`-->`存至REDIS`-->`輸出第一頁之店家結果內容`

- **專案特色**
- Intent-Driven: 直接處理 AI 輸出的結構化意圖 (Logic Tree)。

- Hybrid Search: 結合 關聯式資料庫 (RDBMS) 的精確過濾與 向量資料庫 (Vector DB) 的語意檢索。

- Dynamic SQL Builder: 支援巢狀邏輯 (Nested Logic) 與遞迴解析，自動防止 SQL Injection。

- Repository Pattern: 完善的資料存取層分離，支援 Mock Data 與真實 DB (MySQL/Qdrant) 的無縫切換。

- Dry Run Mode: 支援僅生成 SQL 與預覽向量結果但不執行查詢的模式，方便 Debug 與前端預覽。
- **專案功能**
- 提供: LLM輸出之邏輯樹解析功能
- 提供: 動態生成SQL SCRIPTS功能
- 提供:"使用者目前位置"之地理過濾的附近搜尋功能
- 提供: 透過時間過濾找尋在該時段有營業的店家
- 提供: "使用者指定'行政區/街/路/鄉/"只要在店家地址字串中有出現的就可以被搜尋到
- 提供: 透過店家名稱查詢特定店家,
- 提供: 提供透過食物種類,菜系,軟服務標籤(只要評論中有提到的)進行查詢美食店家
- 提供: 店家的混和排序功能: 排序規則為:食物種類與蔡系為主要意圖走嚴格的門檻過濾並改成`1.0`在傳統邏輯閘中實現嚴格的布林值過濾,軟屬性標籤透過(OR)加權越多項符合的排名越前面

- **專案結構**
```
Search_api/
├── app/
│   ├── __init__.py           # Flask App 工廠模式
│   ├── routes/               # API 路由 (Controller)
│   │   └── place_search_bp.py
│   ├── services/             # 核心業務邏輯
│   │   ├── hybrid_sql_builder_service_v2.py  # SQL 生成器
│   │   ├── hard_filtering_service.py         #　時間之店家硬性過濾
│   │   └── vector_service.py                 # 向量服務 Facade
│   ├── repositories/         # 資料存取層
│   │   ├── rdbms_repository.py   # MySQL/MariaDB I/O操作
│   │   └── vector_repository.py  # Qdrant/Milvus I/O操作 
│   └── models/               # 資料模型 (DTO)
|       └── search_dto.py     # 向量資料庫查詢資料物件定義
|   
├── utils/
│   └── db.py                 # 資料庫連線池管理
├── config.py                 # 環境變數配置
├── run.py                    # 啟動腳本
├── requirements.txt          # 套件依賴
└── README.md
```
## Deploy Guide (部署指南)
1. 環境需求 (Prerequisites)
- 本專案使用 Python 3.10.11
- 

- MySQL / MariaDB (Optional, currently supports Mock)

- Qdrant / Milvus (Optional, currently supports Mock)

2. 安裝步驟 (Installation)
- Clone 專案

```
git clone https://github.com/your-repo/search-api.git
```
```
cd search-api
```
- 建立虛擬環境

```

python -m venv venv
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate
```

- 安裝依賴套件

```

pip install -r requirements.txt
```
(主要套件包含: flask, pymysql, qdrant-client, sentence-transformers)

- 環境變數設定 (.env) 請在根目錄建立 .env 檔案：

```
# 關聯式資料庫連線資訊
DB_HOST=192.168.1.112
DB_PORT=4404
DB_USER=root
DB_PASSWORD=User@534
DB_NAME=foodchatbot_database

# 向量資料庫連線資訊
VECTOR_DB_HOST = 192.168.1.112
Vector_DB_PORT=6333
COLLECTION_NAME = restaurants_0326
# 照片網址
IMAGES_URL = "http://192.168.1.112:5003/images/"

# --- 效能監控與測試設定 ---
# 搜尋架構名稱 (例如: Hybrid_V2_Original, Hybrid_V2_Optimized)
SEARCH_ARCHITECTURE=Hybrid_V2_Full_Flow

# 目前資料庫總筆數 (用於 CSV 紀錄對照，手動填寫目前測試規模)
CURRENT_PLACE_COUNT=3200 

# 效能日誌 CSV 儲存路徑
PERFORMANCE_LOG_PATH=logs/performance_metrics.csv

# Redis 連線資訊
# 在 Docker Compose 網路中，可以直接用容器名稱當作 Host
REDIS_HOST=192.168.1.118
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
```

3. 啟動伺服器 (Run)
```
python run.py
```
伺服器將預設運行於 http://127.0.0.1:5003

