import os
import json
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
# 2. 資料處理邏輯 (對齊 Data-Centric AI 精神)
# ==========================================
import uuid

def uuid_to_uint64(uuid_str):
    """將 UUID 字串轉為 64-bit 整數"""
    return uuid.UUID(uuid_str).int & ((1 << 64) - 1)

def prepare_data_for_import(file_path):
    """讀取 JSON 並合成與查詢端 100% 對齊的高品質 Passage"""
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

        # 🌟 修正：改用 vdb_id 作為核心 ID，避免多筆評論 ID 重複導致覆蓋
        vdb_id_str = item.get('vdb_id')
        if not vdb_id_str:
            logging.error(f"❌ 警告：資料項目缺失核心 vdb_id，跳過此筆。項目: {item.get('name')}")
            continue
        
        # 將 UUID 轉為 uint64
        try:
            db_id = uuid_to_uint64(vdb_id_str)
        except Exception as e:
            logging.error(f"❌ 警告：vdb_id 轉換失敗 ({vdb_id_str})，跳過此筆。錯誤: {e}")
            continue

        name = str(item.get('name', '未知餐廳'))
        cuisine_types = clean_tags(item.get('cuisine_type', []))
        merchant_category = clean_tags(item.get('merchant_category', []))
        food_types = clean_tags(item.get('food_type', []))
        flavors = clean_tags(item.get('flavor', []))
        review_summary = item.get('review_summary', '暫無評論摘要')
        f_tags = clean_tags(item.get('facility_tags', []))

        if name == 'nan' or not any([cuisine_types, food_types, flavors]):
            continue

        # 🎯 終極優化：語意描述句全面與 VectorService 端完成闭环對齊
        passage = (
            f"這家餐廳的店名是【{name}】，在商戶類別上屬於：{'/'.join(merchant_category)}。 | "
            f"這家店的料理風格、特色風味與主打菜系屬於：{'/'.join(cuisine_types)}。 | "
            f"這家餐廳的主營餐點、菜單品項與販售的食物種類包含：{'/'.join(food_types)}。 | "
            f"具體的口味特徵與口感表現為：{'/'.join(flavors)}。 | "
            f"這家餐廳店內提供的服務、硬體設備、友善設施或環境包含：{'/'.join(f_tags)}。 | "
            f"顧客對這家餐廳的深度評價摘要與熱門評論觀點：{review_summary}"
        )

        processed_data.append({
            "id": int(db_id),  # 確保是整數型態，符合 Qdrant uint64 規格
            "text_to_embed": passage,
            "payload": item
        })

    logging.info(f"資料轉換與語意對齊完成，共 {len(processed_data)} 筆有效資料。")
    return processed_data

# ==========================================
# 3. Qdrant 操作邏輯
# ==========================================
def start_import_qdrant(model, json_path, collection_name, host, port=6333, batch_size=64):
    """執行批次向量化與匯入"""
    client = QdrantClient(host=host, port=port)
    
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
        
        # 🌟 效能優化：開啟 normalize_embeddings=True，加速 Qdrant 建立 HNSW 索引
        texts = [item["text_to_embed"] for item in batch]
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_tensor=False).tolist()

        points = [
            PointStruct(
                id=item["id"],        # 這裡已經是乾淨的 MySQL 整數 ID
                vector=vectors[j],
                payload=item["payload"]
            ) for j, item in enumerate(batch)
        ]

        client.upsert(collection_name=collection_name, points=points)
        logging.info(f"📈 匯入進度: {min(i + batch_size, total)} / {total}")

    logging.info("🎉 匯入任務與語意空間投影完美圓滿完成！")

# ==========================================
# 主執行入口
# ==========================================
if __name__ == "__main__":
    init_logging()
    device = check_env()

    MODEL_PATH = "./m3_food_finetuned"  
    DATA_JSON = "cleaned_restaurants_20260520_20260607.json"
    COLLECTION_NAME = "restaurants_20260520"
    QDRANT_HOST = "192.168.0.201"

    if not os.path.exists(MODEL_PATH):
        logging.warning("找不到微調模型，將使用 BAAI/bge-m3 預訓練權重")
        MODEL_PATH = "BAAI/bge-m3"
    
    logging.info(f"正在載入 Embedding 模型: {MODEL_PATH}")
    model = SentenceTransformer(MODEL_PATH, device=device)

    start_import_qdrant(
        model=model,
        json_path=DATA_JSON,
        collection_name=COLLECTION_NAME,
        host=QDRANT_HOST,
        batch_size=64  # 在雙 GPU 或者是 4060Ti 16G 顯存下，甚至可以嘗試開到 128
    )