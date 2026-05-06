import os
import json
import uuid
import logging
import torch
from datetime import datetime
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance

# ==========================================
# 1. 系統與日誌初始化
# ==========================================
def init_logging(log_dir="logs"):
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_filename = datetime.now().strftime("import_%Y%m%d_%H%M%S.log")
    log_path = os.path.join(log_dir, log_filename)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    logging.info(f"匯入系統日誌初始化完成: {log_path}")

def check_env():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logging.info(f"運算設備: {device.upper()}")
    if device == "cuda":
        logging.info(f"顯卡型號: {torch.cuda.get_device_name(0)}")
    return device

# ==========================================
# 2. 資料處理邏輯
# ==========================================
def prepare_data_for_import(file_path):
    """讀取 JSON 並合成高品質的 Passage"""
    if not os.path.exists(file_path):
        logging.error(f"找不到來源檔案: {file_path}")
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    processed_data = []
    for item in data:
        def clean_tags(tags):
            if not isinstance(tags, list): return []
            return [str(t).strip() for t in tags if str(t).lower() != 'nan' and t]

        name = str(item.get('name', '未知餐廳'))
        cuisine_types = clean_tags(item.get('cuisine_type', []))
        merchant_category = clean_tags(item.get('merchant_category', []))
        food_types = clean_tags(item.get('food_type', []))
        flavors = clean_tags(item.get('flavor', []))
        review_summary = item.get('review_summary', '')
        f_tags = clean_tags(item.get('facility_tags', []))

        # 過濾掉資訊嚴重缺失的資料
        if name == 'nan' or not any([cuisine_types, food_types, flavors]):
            continue

        # 構造用於 Embedding 的 Passage：強調餐廳屬性與語境
        passage = (
            f"店名與餐廳類型：{name}、{'/'.join(merchant_category)} | "
            f"主打菜系與食物：{'/'.join(cuisine_types)}、{'/'.join(food_types)} | "
            f"口味特徵：{'/'.join(flavors)} | " 
            f"服務設施與特色：{'/'.join(f_tags)} | "
            f"深度評價摘要：{review_summary}"
        )

        processed_data.append({
            "id": str(uuid.uuid4()),
            "text_to_embed": passage,
            "payload": item  # 將原始 JSON 資料全部存入 Payload 供查詢返回
        })

    logging.info(f"資料轉換完成，共 {len(processed_data)} 筆有效資料。")
    return processed_data

# ==========================================
# 3. Qdrant 操作邏輯
# ==========================================
def start_import_qdrant(model, json_path, collection_name, host, port=6333, batch_size=64):
    """執行批次向量化與匯入"""
    client = QdrantClient(host=host, port=port)
    
    # 檢查並建立 Collection (BGE-M3 維度為 1024)
    try:
        client.get_collection(collection_name)
        logging.info(f"✅ 使用既有 Collection: {collection_name}")
    except Exception:
        logging.info(f"⚠️ 建立新 Collection: {collection_name}")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )

    import_data = prepare_data_for_import(json_path)
    if not import_data: return

    total = len(import_data)
    logging.info(f"🚀 開始匯入流程，總數: {total}, Batch Size: {batch_size}")

    for i in range(0, total, batch_size):
        batch = import_data[i : i + batch_size]
        
        # GPU 批次處理文字轉向量
        texts = [item["text_to_embed"] for item in batch]
        vectors = model.encode(texts, convert_to_tensor=False).tolist()

        # 組裝 PointStruct
        points = [
            PointStruct(
                id=item["id"],
                vector=vectors[j],
                payload=item["payload"]
            ) for j, item in enumerate(batch)
        ]

        client.upsert(collection_name=collection_name, points=points)
        logging.info(f"📈 進度: {min(i + batch_size, total)} / {total}")

    logging.info("🎉 匯入任務圓滿完成！")

# ==========================================
# 主執行入口
# ==========================================
if __name__ == "__main__":
    init_logging()
    device = check_env()

    # 配置區域
    MODEL_PATH = "./m3_food_finetuned"  # 指向你微調後的模型路徑
    DATA_JSON = "restaurants_20260326_all_fixed.json"
    COLLECTION_NAME = "restaurants"
    QDRANT_HOST = "192.168.1.112"

    # 1. 載入模型
    if not os.path.exists(MODEL_PATH):
        logging.warning("找不到微調模型，將使用 BAAI/bge-m3 預訓練權重")
        MODEL_PATH = "BAAI/bge-m3"
    
    logging.info(f"正在載入 Embedding 模型: {MODEL_PATH}")
    model = SentenceTransformer(MODEL_PATH, device=device)

    # 2. 執行匯入
    start_import_qdrant(
        model=model,
        json_path=DATA_JSON,
        collection_name=COLLECTION_NAME,
        host=QDRANT_HOST,
        batch_size=64  # 如果顯存夠大 (如 4060Ti 16G)，可調至 128
    )