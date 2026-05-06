# AI Hybrid Search API (RAG Backend)
- 這是一個專為 AI 搜尋場景設計的後端系統。它採用 Hybrid Search (混合搜尋) 架構，能夠接收來自 LLM (Large Language Model) 解析後的 JSON 意圖，動態生成 -SQL 查詢語句，並結合向量資料庫 (Vector DB) 的語意搜尋結果，實現RAG (Retrieval-Augmented Generation) 檢索的功能。

- **專案特色**
- Intent-Driven: 直接處理 AI 輸出的結構化意圖 (Logic Tree)。

- Hybrid Search: 結合 關聯式資料庫 (RDBMS) 的精確過濾與 向量資料庫 (Vector DB) 的語意檢索。

- Dynamic SQL Builder: 支援巢狀邏輯 (Nested Logic) 與遞迴解析，自動防止 SQL Injection。

- Repository Pattern: 完善的資料存取層分離，支援 Mock Data 與真實 DB (MySQL/Qdrant) 的無縫切換。

- Dry Run Mode: 支援僅生成 SQL 與預覽向量結果但不執行查詢的模式，方便 Debug 與前端預覽。

- **專案結構**
```
Search_api/
├── app/
│   ├── __init__.py           # Flask App 工廠模式
│   ├── routes/               # API 路由 (Controller)
│   │   └── place_search_bp.py
│   ├── services/             # 核心業務邏輯
│   │   ├── hybrid_sql_builder_service_v2.py  # SQL 生成器
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

## API Testing Guide (測試指南)
- 本系統目前支援 Mock Mode (模擬模式)，即便沒有安裝真實資料庫也能進行測試。

- Endpoint
- URL: POST /place_search/search

- Content-Type: application/json

- 測試情境範例 (Test Cases)
- 可以使用 Postman 或 curl 測試以下情境。

- **情境一：混合搜尋 (Hybrid Search)**
- 描述：找「台南」的「牛肉湯」，且口感要「鮮甜」，評分 > 4.0。 觸發機制：flavor 欄位觸發向量搜尋，address 與 rating 觸發 SQL。

```

{
    "main_intent": "recommend",
    "info_needed": ["name", "address", "rating"],
    "vector_keywords": ["鮮甜"],
    "logic_tree": {
        "op": "AND",
        "conditions": [
            { "address": { "cmp": "LIKE", "value": "%台南%" } },
            { "merchant_category": { "cmp": "=", "value": "牛肉湯" } },
            { "rating": { "cmp": ">=", "value": 4.0 } },
            { "flavor": { "cmp": "=", "value": "鮮甜" } }
        ]
    }
}
```
- **情境二：純向量搜尋 (Vector Only)**
- 描述：只在意口感「濃郁」或「酥脆」，不在意地點。 觸發機制：vector_needed 為 True，SQL WHERE 僅包含 ID Filter。

```

{
    "main_intent": "recommend",
    "info_needed": ["name", "review_text"],
    "logic_tree": {
        "op": "OR",
        "conditions": [
            { "flavor": { "cmp": "=", "value": "濃郁" } },
            { "flavor": { "cmp": "=", "value": "酥脆" } }
        ]
    }
}
```
- **情境三：複雜邏輯過濾 (Complex SQL)**
- 描述：找「中西區」的店，要是「老店」或者評分高於 4.2。 觸發機制：巢狀 AND / OR 邏輯解析。

```

{
    "main_intent": "filter",
    "info_needed": ["name", "service_tags"],
    "logic_tree": {
        "op": "AND",
        "conditions": [
            { "address": { "cmp": "LIKE", "value": "%中西區%" } },
            {
                "op": "OR",
                "conditions": [
                    { "service_tags": { "cmp": "LIKE", "value": "%老店%" } },
                    { "rating": { "cmp": ">", "value": 4.2 } }
                ]
            }
        ]
    }
}
```
- 回傳格式說明 (Response)
- 系統會回傳包含「向量檢索詳情」、「生成的 SQL」與「最終模擬結果」的完整資訊：

```

{
    "status": "success",
    "mode": "dry_run_with_mock_data",
    "data": {
        "vector_search_info": {
            "keywords": ["鮮甜"],
            "found_ids": [201, 206],
            "details": [...]
        },
        "generated_query": {
            "sql": "SELECT ... FROM ... WHERE p.address LIKE %(p0)s AND p.id IN (201,206) ...",
            "params": { "p0": "%台南%" }
        },
        "final_results": [
            { "id": 206, "name": "文章牛肉湯", "rating": 4.6, ... }
        ]
    }
}

```

- **切換至真實資料庫**
- 若要切換至 Production 模式，請修改 app/repositories/ 下的 Repository 初始化參數：

- 開啟 app/routes/place_search_bp.py

- 修改初始化參數 use_mock=False：

```

vector_repo = VectorRepository(use_mock=False)
rdbms_repo = RdbmsRepository(use_mock=False)

```
- 確保 .env 中的資料庫連線資訊設定正確。