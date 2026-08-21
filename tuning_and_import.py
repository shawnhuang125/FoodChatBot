import os
import json
import logging
import torch
import uuid
from datetime import datetime
from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    PointStruct,
    VectorParams,
    Distance,
    MultiVectorConfig,
    MultiVectorComparator
)

def init_logging(log_dir="logs"):
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_filename = datetime.now().strftime("import_multivector_%Y%m%d_%H%M%S.log")
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
    logging.info(f"匯入日誌初始化完成: {log_path}")

def check_env():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logging.info(f"運算設備: {device.upper()}")
    if device == "cuda":
        logging.info(f"顯卡型號: {torch.cuda.get_device_name(0)}")
    return device

def uuid_to_uint64(uuid_str: str) -> int:
    return uuid.UUID(uuid_str).int & ((1 << 64) - 1)


ARRAY_FIELDS = ["cuisine_type", "food_type", "flavor", "facility_tags", "service_tags"]
SINGLE_FIELDS = ["review_summary", "passage_all"]

def clean_tags(tags) -> List[str]:
    if not isinstance(tags, list):
        return []
    return [str(t).strip() for t in tags if str(t).lower() != 'nan' and str(t).strip()]

def start_import_multivector_qdrant(
    model: SentenceTransformer,
    json_path: str,
    collection_name: str,
    host: str,
    port: int = 6333,
    batch_size: int = 64
):
    client = QdrantClient(host=host, port=port)
    vector_dim = model.get_sentence_embedding_dimension() or 1024

    # 1. 建立向量配置（啟用 cuisine_type_vector 等命名向量）
    vectors_config = {}
    
    # 陣列型維度：啟用 Multi-Vector MaxSim 比較器
    for name in ARRAY_FIELDS:
        vector_name = f"{name}_vector"
        vectors_config[vector_name] = VectorParams(
            size=vector_dim,
            distance=Distance.COSINE,
            multivector_config=MultiVectorConfig(
                comparator=MultiVectorComparator.MAX_SIM
            )
        )
    
    # 單文本維度：標準單向量
    for name in SINGLE_FIELDS:
        vector_name = f"{name}_vector"
        vectors_config[vector_name] = VectorParams(
            size=vector_dim,
            distance=Distance.COSINE
        )

    try:
        client.get_collection(collection_name)
        logging.info(f"✅ 使用既有 Collection: {collection_name}")
    except Exception:
        logging.info(f"⚠️ 建立新多向量 Collection: {collection_name}")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=vectors_config
        )

    if not os.path.exists(json_path):
        logging.error(f"找不到來源檔案: {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    # 2. 全域標籤快取字典
    tag_embedding_cache: Dict[str, List[float]] = {}
    zero_vector = [0.0] * vector_dim

    def encode_tags_to_multivector(tags: List[str]) -> List[List[float]]:
        """將陣列中的每個元素獨立轉為向量，回傳 2D 矩陣 List[List[float]]"""
        if not tags:
            return [zero_vector]
        
        uncached = [t for t in tags if t not in tag_embedding_cache]
        if uncached:
            encoded_batch = model.encode(
                uncached,
                normalize_embeddings=True,
                convert_to_tensor=False
            ).tolist()
            for t, vec in zip(uncached, encoded_batch):
                tag_embedding_cache[t] = vec

        return [tag_embedding_cache[t] for t in tags]

    # 3. 資料前處理
    processed_items = []
    for item in raw_data:
        vdb_id_str = item.get('vdb_id')
        if not vdb_id_str:
            continue
        try:
            db_id = uuid_to_uint64(vdb_id_str)
        except Exception:
            continue

        name = str(item.get('name', '未知餐廳')).strip()
        cuisine_types = clean_tags(item.get('cuisine_type', []))
        food_types = clean_tags(item.get('food_type', []))
        flavors = clean_tags(item.get('flavor', []))
        facility_tags = clean_tags(item.get('facility_tags', []))
        service_tags = clean_tags(item.get('service_tags', []))
        merchant_cat = clean_tags(item.get('merchant_category', []))

        review_summary = str(item.get('review_summary', '')).strip()
        if not review_summary or review_summary == "暫無精選評論摘要":
            review_summary = "暫無評論摘要"

        if name == 'nan' or not any([cuisine_types, food_types, flavors]):
            continue

        passage_all = (
            f"店名【{name}】，類別：{'/'.join(merchant_cat)}。|"
            f"菜系風格：{'/'.join(cuisine_types)}。|"
            f"餐點種類：{'/'.join(food_types)}。|"
            f"口味特色：{'/'.join(flavors)}。|"
            f"設施服務：{'/'.join(facility_tags + service_tags)}。|"
            f"評價摘要：{review_summary}"
        )

        processed_items.append({
            "id": int(db_id),
            "arrays": {
                "cuisine_type": cuisine_types,
                "food_type": food_types,
                "flavor": flavors,
                "facility_tags": facility_tags,
                "service_tags": service_tags
            },
            "singles": {
                "review_summary": f"顧客精選評論觀點：{review_summary}",
                "passage_all": passage_all
            },
            "payload": item
        })

    total = len(processed_items)
    logging.info(f"🚀 開始寫入 Qdrant，總數: {total}, Batch Size: {batch_size}")

    # 4. 批次推論與寫入
    for i in range(0, total, batch_size):
        batch = processed_items[i : i + batch_size]

        single_vectors: Dict[str, list] = {}
        for s_key in SINGLE_FIELDS:
            texts = [item["singles"][s_key] for item in batch]
            single_vectors[s_key] = model.encode(
                texts,
                normalize_embeddings=True,
                convert_to_tensor=False,
                batch_size=batch_size
            ).tolist()

        points = []
        for j, item in enumerate(batch):
            vector_dict = {}
            
            # 陣列欄位：包含 cuisine_type_vector
            for a_key in ARRAY_FIELDS:
                vector_dict[f"{a_key}_vector"] = encode_tags_to_multivector(item["arrays"][a_key])

            # 單向量欄位
            for s_key in SINGLE_FIELDS:
                vector_dict[f"{s_key}_vector"] = single_vectors[s_key][j]

            points.append(
                PointStruct(
                    id=item["id"],
                    vector=vector_dict,
                    payload=item["payload"]
                )
            )

        client.upsert(collection_name=collection_name, points=points)
        logging.info(f"📈 匯入進度: {min(i + batch_size, total)} / {total} (快取標籤數: {len(tag_embedding_cache)})")

    logging.info("🎉 命名向量匯入完成！")

if __name__ == "__main__":
    init_logging()
    device = check_env()

    MODEL_PATH = "./models/bge_m3"
    DATA_JSON = "cleaned_restaurants_20260520_20260607.json"
    COLLECTION_NAME = "restaurants_20260520_20260816"
    QDRANT_HOST = "192.168.0.206"

    if not os.path.exists(MODEL_PATH):
        MODEL_PATH = "BAAI/bge-m3"

    model = SentenceTransformer(MODEL_PATH, device=device)
    start_import_multivector_qdrant(
        model=model,
        json_path=DATA_JSON,
        collection_name=COLLECTION_NAME,
        host=QDRANT_HOST,
        batch_size=64
    )