# AI Hybrid Search API (RAG Backend)
- 這是一個採用混合式檢索架構的餐飲搜尋系統．主要透過關聯式資料庫進行地理初步過濾，地理過濾後檢查用戶需求進行時間過濾，再者向量資料庫進行語意檢索，最後使用非線性對數聚合算子進行餐飲店家重排，重排後將餐飲店家已每三筆進行分頁．將當次查詢之完整分頁內容存至Redis暫存．提供後續 RAG Controller(全域資料連結控制中樞子系統)進行的查尋節果店家卡片生成．
- **主流程**
- `解析智慧AGENT與MCP工具整合服務子系統生成之邏輯樹與查詢相關參數`-->`SQL地理預過濾`-->`時間過濾`-->`相似度需求檢索`-->`混和精排演篹法`-->`店家資料統一美觀處理`-->`存至REDIS`-->`輸出第一頁之店家結果內容`

- **專案結構**
```
Search_api/
├── app/
│   ├── __init__.py           # Flask App 工廠模式
│   ├── routes/               # API 路由 (Controller)
│   │   └── place_search_bp.py
│   ├── services/             # 核心業務邏輯
│   │   ├── hybrid_sql_builder_service_v2.py  # SQL 生成器與邏輯樹清洗模組
│   │   ├── hard_filtering_service.py         #　時間過濾模組
│   │   └── vector_service.py                 # 向量服務 Facade
│   ├── repositories/         # 資料存取層
│   │   ├── rdbms_repository.py   # MySQL/MariaDB I/O操作
│   │   └── vector_repository.py  # Qdrant/Milvus I/O操作 
│   ├── models/               # 資料模型 (DTO)
|   │    └── search_dto.py     # 向量資料庫查詢資料物件定義
|   ├── utils/
|   |   ├── app_logger.py         # 產生本子系統之詳細的存取日誌記錄
|   |   ├── data_formatter.py     # 將查詢到的店家結果進行營業時間，設施標籤與距離的資料格式化
|   |   ├── distance_utils.py     # 封裝 Haversine 距離公式，用於生成第一階段 RDB 空間半徑預過濾的 WHERE 子句
|   |   ├── performance_tracker.py # 記錄 Route 層的整體搜尋效能並儲存於: Config.PERFORMANCE_LOG_PATH
|   |   ├── quality_checker.py     # 合併狀態診斷與品質評價。技術診斷門面：檢查搜尋過程狀態、位置來源及 SQL 命中統計
|   |   ├── search_session_cache.py # 負責管理搜尋結果的 Redis 分頁快取。
|   |   ├── security.py             # 用於處理來源之IP白名單存取功能
|   |   ├── time_checker.py         # 用於將店家營業時間的資料進行統一的格式化，確保JSON的資料正確性．
|   │   └── db.py                 # 資料庫連線池管理
|   └── config.py                 # 環境變數配置
├── run.py                    # 啟動腳本
├── .dockerignore             # 定義哪些檔案與目錄會被Dockerfile在建立映像檔時忽略
├── Dockerfile                # 儲存Docker Compose建立映像檔的執行順序腳本
├── .env.example              # 可以直接複製內容建立一份新的.env用於部署的時候設定完整的環境變數
├── .gitignore                # 用於定義哪些檔案與目錄會在git push的時候會被忽略   
├── .entrypoint.sh            # 用於配合Dockerfile在映像檔建立時透過輸出日誌確定嵌入模型是否掛載成功
├── .gitattributes              # 強制規範專案中特定檔案的「換行符號（End of Line, EOL）」，主要是為了解決 Windows 與 Linux/Docker 跨平台協作時的相容性問題
├── requirements.txt          # 套件依賴
└── README.md
```

- **專案特色**
- Intent-Driven: 直接處理`智慧AGENT與MCP工具整合服務子系統`輸出的結構化意圖 (Logic Tree)。

- Hybrid Search: 結合 關聯式資料庫 (RDBMS) 的精確過濾與 向量資料庫 (Vector DB) 的語意檢索。

- Dynamic SQL Builder: 支援巢狀邏輯 (Nested Logic) 與遞迴解析，自動防止 SQL Injection。

- Pre-Order DFS蒐集語意與時間過濾意圖：為了實現時間過濾，地理過濾與語意檢索之責任分離，本子系統使用前序深度優先走訪（Pre-Order DFS），由上而下傳遞父節點之運算符，於葉節點過濾時間條件，並全面截取語意條件之關鍵字與相對應的特徵權重．

- Post-Order DFS建構語意搜尋邏輯樹： 為了讓向量資料庫的語意檢索功能可以實現完整的布林邏輯閘功能（AND | OR | NOT），本子系統使用後序深度優先走訪（Post-Order DFS），由底而上將非涉及向量資料庫之檢索條件剔除，僅保留語意檢索之原始邏輯嵌套架構．建立語意檢索的專屬邏輯樹．

- 後序求值型 DFS（Post-order AST Evaluation）建構SQL語法： 為了確保建構SQL語法的邏輯優先順序，本子系統採用後序求值型DFS，先走訪至最深的葉節點，將葉節點生成SQL語法片段，一路透過父節點將有關於SQL的過濾條件
進行邏輯上的語法片段拼接，實現保持運算子優先順序的功能．

- Repository Pattern: 為了確保開發上的嚴謹性，本子系統將路由，業務邏輯，資料庫I/O操作分開，進行全責分離的設計，確保程式碼的擴展性與可閱讀性，確保不會有漏改程式碼的問題，統一透過自訂義物件之呼叫函式．

- **專案功能**
- 提供: LLM輸出之邏輯樹解析功能
- 提供: 動態生成SQL SCRIPTS功能
- 提供:"使用者目前位置"之地理過濾的附近搜尋功能
- 提供: 透過時間過濾找尋在該時段有營業的店家
- 提供: "使用者指定'行政區/街/路/鄉/"只要在店家地址字串中有出現的就可以被搜尋到
- 提供: 透過店家名稱查詢特定店家,
- 提供: 提供透過食物種類,菜系,軟服務標籤(只要評論中有提到的)進行查詢美食店家
- 提供: 店家的混和排序功能: 排序規則為:食物種類與蔡系為主要意圖走嚴格的門檻過濾並改成`1.0`在傳統邏輯閘中實現嚴格的布林值過濾,軟屬性標籤透過(OR)加權越多項符合的排名越前面



### Docker Compose 部署指南(windows)
1. 將專案複製到指定之伺服器內
2. 解壓縮
3. 進入到專案跟目錄
```
cd Search_API_v4.4.2.2.3/
```
4. 環境變數設定 (.env) 請在根目錄建立 .env 檔案：

```
cp .env.example .env
```
- 填入實際參數：手動編輯 .env 中的密碼、連線 IP 與 Host 即完成配置。
5. 跳出去專案目錄
```
cd ..
```
6. 掛載嵌入模型

- 把模型絕對路徑掛載到volumn裡面(其餘的頃都不要亂動)

```
search-api:
    build:
      context: ./Search_API_v4.3.0
      dockerfile: Dockerfile         
    image: search-api:latest
    container_name: search-api-container
    restart: always
    ports:
      - "5004:5004"
    # .env 檔放在 Search_API_v4.3.0  資料夾內
    env_file:
      - ./Search_API_v4.3.0/.env
    volumes:
      - "[嵌入模型的絕對路徑]:/models/bge_m3:ro"
    networks:
      backend_net:
        ipv4_address: 172.28.0.2     

    # 等 Redis 健康檢查通過才啟動，防止 API 啟動時 Redis 還沒就緒
    depends_on:
      redis:
        condition: service_healthy

    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```
- 按下`ctrl`+`s`存檔後即可離開


6. 啟動docker compose服務
```
docker compose up -d
```
7. 查看服務狀態
```
docker compose logs -f
```

