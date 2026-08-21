# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev_key") # 如果沒有flask需要使用的SECRET_KEY參數則預設為dev_key
    COLLECTION_NAME = os.getenv("COLLECTION_NAME", "")
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1") # 如果沒有資料庫host,預設為127.0.0.1也就是本機端連線
    DB_PORT = int(os.getenv("DB_PORT", 3306)) # 如果沒有資料庫Port,預設為3306
    DB_USER = os.getenv("DB_USER", "root") # 如果沒有資料庫user,預設為root
    DB_PASSWORD = os.getenv("DB_PASSWORD", "") # 如果沒有資料庫密碼,預設為空
    DB_NAME = os.getenv("DB_NAME", "") # 如果沒有資料庫名稱,預設為空
    # 資料庫連線url
    DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    # 讀取照片之網址
    IMAGES_URL = os.getenv("IMAGES_URL", "http://localhost/images/")
    # 讀取向量資料庫之配置ip與port
    VECTOR_DB_HOST = os.environ.get('VECTOR_DB_HOST', 'localhost')
    VECTOR_DB_PORT = int(os.environ.get('VECTOR_DB_PORT', 6333))
    # 讀取效能測試之相關參數
    SEARCH_ARCHITECTURE = os.getenv("SEARCH_ARCHITECTURE", "Default_Hybrid")
    CURRENT_PLACE_COUNT = os.getenv("CURRENT_PLACE_COUNT", "0")
    PERFORMANCE_LOG_PATH = os.getenv("PERFORMANCE_LOG_PATH", "performance_metrics.csv")
    # 從環境變數檔案中讀取遷墓模型之掛載路徑
    EMBEDDING_MODEL_PATH = os.getenv("EMBEDDING_MODEL_PATH", "/models/bge_m3")
    # -------- Redis 連線設定（用於搜尋分頁 Session 快取）--------
    # 為什麼這樣做：Redis 支援跨 Worker 共享，解決 in-memory dict 無法水平擴展的問題
    REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB   = int(os.getenv("REDIS_DB", 0))          # 使用 DB 0，與其他業務隔離可改為其他數字
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)   # 本機開發通常為空，生產環境應設定密碼

    # 搜尋 Session 的存活時間（秒）
    # 為什麼是 600 秒：給使用者 10 分鐘的翻頁窗口，兼顧體驗與記憶體節省
    SEARCH_SESSION_TTL = int(os.getenv("SEARCH_SESSION_TTL", 600))

    # 每頁回傳的店家筆數（固定為 3，與原本 top_k 語意對齊）
    PAGE_SIZE = int(os.getenv("PAGE_SIZE", 3))

    # -------- IP 白名單設定 --------
    # 將逗號分隔的 IP 字串轉為 set，加速 FastAPI 的 O(1) 搜尋比對
    ALLOWED_IPS = set(
        ip.strip() for ip in os.getenv("ALLOWED_IPS", "127.0.0.1,172.24.48.1,172.28.0.1,localhost").split(",") if ip.strip()
    )