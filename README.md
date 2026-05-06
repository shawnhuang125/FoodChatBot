# Restaurant Info & Image Service API

- 這是一個基於 **FastAPI** 開發的後端服務，主要負責提供店家的詳細資訊（包含營業時間、餐點類型、設施等）以及對應的店家照片串流服務。

## 功能特點

* **店家詳細資訊查詢**：整合資料庫欄位與 `PlaceAttribute` 關聯資料，提供完整的店家畫像。
* **動態照片匹配**：根據店家 ID 自動掃描本地目錄，動態生成可供前端直接訪問的照片 URL 清單。
* **競態條件 (Race Condition) 防護**：API 回傳包含請求時傳入的 `sid`，確保前端在異步載入多個店家時不會發生資料錯置。
* **安全性強化**：圖片服務內建 **目錄穿越 (Directory Traversal)** 防護，防止非法存取伺服器敏感檔案。
* **強健的日誌系統**：透過自定義 `logger` 完整記錄 API 請求、檔案存取狀態及系統異常。


## API 接口說明

### 1. 取得店家詳細資訊
- 取得特定店家的詳細屬性、解析後的營業時間及匹配的照片清單。

* **Endpoint:** `GET /get_place_info/{pid}`
* **Query Parameters:**
    * `sid` (string): 請求識別碼（由前端產生，用於校驗回傳順序）。
* **Path Parameters:**
    * `pid` (int): 店家唯一 ID。

**回應範例：**
```json
{
    "status": "success",
    "sid": "xxxxxx",
    "data": {
        "id": xxx,
        "name": "--------------------------------",
        "address": "--------------------------------",
        "lat": xx.xxxxxxx,
        "lng": xx.xxxxxxx,
        "phone": "---------",
        "website": "--------------------------------------------------",
        "map_url": "--------------------------------------------------",
        "opening_hours": {
            "星期一": "10:45 - 21:00",
            "星期二": "10:45 - 21:00",
            "星期三": "10:45 - 21:00",
            "星期四": "10:45 - 21:00",
            "星期五": "10:45 - 21:00",
            "星期六": "10:45 - 21:00",
            "星期日": "休息"
        },
        "rating": 4.9,
        "attributes_tags": [
            "麵食",
            "小吃",
            "中式料理",
            "台式料理"
        ],
        "merchant_category": "店面",
        "facility_tags": [
            "外帶"
        ],
        "photos": [
            "http://192.168.1.112:5003/images/04001.jpg",
            "http://192.168.1.112:5003/images/04002.jpg",
            "http://192.168.1.112:5003/images/04003.jpg",
            "http://192.168.1.112:5003/images/04004.jpg",
            "http://192.168.1.112:5003/images/04005.jpg",
            "http://192.168.1.112:5003/images/04006.jpg",
            "http://192.168.1.112:5003/images/04007.jpg",
            "http://192.168.1.112:5003/images/04008.jpg",
            "http://192.168.1.112:5003/images/04009.jpg",
            "http://192.168.1.112:5003/images/04010.jpg"
        ]
    }
}
```
### 2. 靜態圖片服務
- 提供實體照片檔案的串流讀取。

* **Endpoint**: GET /images/{filename}

* **安全機制：**

- 系統會自動將路徑規範化（normpath），並檢查路徑是否以定義的 PHOTOS_DIR 開頭。

- 若偵測到非法的路徑跳轉（如 ../etc/passwd），將回傳 400 Bad Request 並觸發安全警報。

* **照片命名與讀取邏輯**
- 系統採用的照片管理規範如下：

- ID 補零：將店家 ID 補齊至 3 位數（例如 ID 7 轉為 007）。

- 流水號：預設掃描每家店第 01 到 10 張照片。

- 副檔名：統一為 .jpg。

- 範例路徑：店家 ID 為 12，則系統會嘗試尋找 /photos/01201.jpg 至 /photos/01210.jpg。

* **環境變數配置 (.env)**
- 請確保你的 .env 檔案中包含以下變數：
```
# Database Configuration
# set DB_HOST = mysql if you wanna deploy service by docker-compose
DB_HOST =
DB_PORT =
DB_USER =
DB_PASSWORD =
DB_NAME =
# The Photo URL provides users read
IMAGES_BASE_URL = "" 
# The Photo Path that Business API needs to load from
PHOTO_PATH = ""
```

* **營業時間解析**
- 資料庫中 opening_hours 以字串形式儲存，後端在回傳前會執行 json.loads()。若格式有誤，會捕捉 JSONDecodeError 並回傳空字典 {}，確保前端渲染不報錯。

* **效能優化**
- 使用 SQLAlchemy 的 joinedload 預加載關聯表 Restaurant.attributes，避免 N+1 查詢問題。

- 使用 FileResponse 高效率串流大型圖片檔案。

## 部屬說明(適用database+business_api.docker-compose.zip)
- 檢查`docker`環境
```
docker ps -a
```
- 將下載的`database+business_api.docker-compose.zip`解壓縮
```
sudo unzip database+business_api.docker-compose.zip
```
- 檢查是否成功
```
ls
```
要看到類似下面:
```
d-----          5/6/2026   9:02 PM                database+business_api.docker-compose
```
- 進入`docker-compose`資料夾
```
cd database+business_api.docker-compose/docker-compose/
```
- 確認目錄位置內容
```
ls
```
- 應該有下列檔案:
```
Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a----          5/6/2026   9:02 PM          91588 Business_api_v1.0.7.zip
-a----          5/6/2026   9:02 PM           1594 docker-compose.txt
-a----          5/6/2026   9:02 PM           1874 docker-compose.yaml
-a----          5/6/2026   9:02 PM           2788 README.md
```
- 創立一個`.env`,並貼上以下內容:
- `PHOTO_PATH`可以換成你自己的照片目錄位置
- `DB_HOST`換成你自己要部屬的伺服器`IP Address`
```
# Database Configuration
# set DB_HOST = mysql if you wanna deploy service by docker-compose
DB_HOST=192.168.1.112
DB_PORT=4404
DB_USER=user
DB_PASSWORD=User@534
DB_NAME=foodchatbot_database
# The Photo URL provides users read
IMAGES_BASE_URL=http://192.168.1.112:5003/images/
# The Photo Path that Business API needs to load from
PHOTO_PATH=C:/devolopment_projects/Business_api/photos
```

- 使用`docker-compose`部屬服務
```
docker compose up -d
```
- 需等待5-10分鐘
- 檢查服務狀態
```
docker ps -a
```
- 應該和下面一樣:
```
CONTAINER ID   IMAGE                                COMMAND                  CREATED          STATUS                    PORTS                                                             NAMES
1de99d2d9037   docker-compose-business-api_v1.0.7   "uvicorn run:app --h…"   51 seconds ago   Up 19 seconds             0.0.0.0:5003->5003/tcp, [::]:5003->5003/tcp                       business_api_container_v1.0.7
8899ff7651b4   phpmyadmin/phpmyadmin                "/docker-entrypoint.…"   51 seconds ago   Up 19 seconds             0.0.0.0:8080->80/tcp, [::]:8080->80/tcp                           phpmyadmin_container
dd4f26289f36   mysql:8.0                            "docker-entrypoint.s…"   51 seconds ago   Up 50 seconds (healthy)   0.0.0.0:4404->3306/tcp, [::]:4404->3306/tcp                       mysql_container
452a7c44be7c   qdrant/qdrant:latest                 "./entrypoint.sh"        51 seconds ago   Up 50 seconds             0.0.0.0:6333-6334->6333-6334/tcp, [::]:6333-6334->6333-6334/tcp   qdrant_container
```
- 確認`business-api_v1.0.7`服務狀態,應該要跟下面一樣:
```
business_api_container_v1.0.7  | 2026-05-06 12:36:21 [INFO] [PlaceService] - [PhotoService] 初始化完成 | 實體圖片目錄: /app/photos
business_api_container_v1.0.7  | 2026-05-06 12:36:21 [INFO] [PlaceService] - [PhotoService] 初始化完成 | 圖片 Base URL: http://192.168.1.112:5003/images/
business_api_container_v1.0.7  | INFO:     Started server process [1]
business_api_container_v1.0.7  | INFO:     Waiting for application startup.
business_api_container_v1.0.7  | INFO:     Application startup complete.
business_api_container_v1.0.7  | INFO:     Uvicorn running on http://0.0.0.0:5003 (Press CTRL+C to quit)
```
