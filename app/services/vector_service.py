# app/services/vector_service.py
from typing import List, Dict, Any, Optional,Tuple
from app.repository.vector_repository import VectorRepository
from sentence_transformers import SentenceTransformer
from app.models.search_dto import VectorSearchResult
from huggingface_hub import snapshot_download
import numpy as np
import math
from app.utils.app_logger import logger
import numpy as np
import math
import time
import json
import os
import re

    # 本專案之向量搜尋的業務邏輯設計嚴格遵循"宣告式程式設計"
    # 為了提升維護效率與閱讀性所以將業務邏輯與資料庫搜尋之I/O運算分層設計

class RankSettings:


    # -------- 混合排序權重邏輯配置 --------


    # 被排序的所有店家指標: 
    # distance: 距離, rating: 評論星等, popularity: 知名度(總評論數), similarity: 語意相似度
    ALLOWED_FIELDS = {"distance", "rating", "popularity", "similarity"}


    # 補上預設語意優先權重 (當 LLM 沒有傳 sort_conditions 時使用)
    DEFAULT_WEIGHTS = {
        "similarity": 0.50,
        "rating": 0.25,
        "popularity": 0.15,
        "distance": 0.10
    }

    # 補上動態排序的基礎保底矩陣 (也就是你 Log 裡噴找不到的那個)
    DYNAMIC_BASE = {
        "similarity": 0.20,
        "rating": 0.10,
        "popularity": 0.10,
        "distance": 0.10
    }

    # 補上排序條件的權重加權紅利 (Bonus)
    # 當使用者指定某個欄位排序（如評分），該欄位直接權重暴增，符合硬派排序業務
    PRIMARY_BONUS = 0.40    # 第一順位排序欄位加權
    SECONDARY_BONUS = 0.10  # 第二順位排序欄位加權

    # 舊有的基礎物理權重留著備用（如果其他函式有吃到）
    BASE_PHYSICAL_WEIGHTS = {
        "rating": 0.10,
        "popularity": 0.05,
        "distance": 0.05
    }


class VectorService:
    def __init__(self):
        self.model_name = "BAAI/bge-m3"
        # 定義路徑 (確保在 /code/models/bge_m3)
        base_dir = os.getcwd() 
        self.model_path = os.path.abspath(os.path.join(base_dir, "models", "bge_m3"))
        
        # 如果目錄下沒有關鍵檔案 (例如 config.json)，就執行下載
        # 注意：只判斷資料夾存在有時候不保險(可能下載到一半中斷)，判斷 config.json 更嚴謹
        if not os.path.exists(os.path.join(self.model_path, "config.json")):
            logger.info(f"模型檔案不完整，準備下載至 {self.model_path}...")
            os.makedirs(self.model_path, exist_ok=True) 
            
            snapshot_download(
                repo_id=self.model_name,
                local_dir=self.model_path,
                local_dir_use_symlinks=False  # 務必保持 False，否則 Docker 內路徑會出錯
            )
        
        # 載入模型 (路徑完全一致)
        logger.info(f"正在從 {self.model_path} 載入 BGE-M3 嵌入模型...")
        self.model = SentenceTransformer(self.model_path) 
        

        self.model.to('cuda') 
        logger.info("模型載入完成")

        # 初始化 Repo
        self.repo = VectorRepository()



    # 檢查向量需求 - 向量搜尋 - 權重計算與排序
    async def search_and_rank(
        self,
        db_results: List[Dict[str, Any]],
        plan: Dict[str, Any],
        total_count: int = 0,
        **kwargs
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        
        all_vector_results = []
    
        # 獲取當次查詢的 s_id 用於紀錄詳細日誌
        s_id = plan.get("s_id", "unknown_sid")

        # 直接拿 SQLBuilder 解析好的成果，徹底移除非必要的二次重複讀取與賦值
        keywords = plan.get("vector_keywords", {})
        runtime_config = plan.get("matrix_runtime_config", {})
        logical_op = runtime_config.get("op", "AND").upper() 
        llm_weights = runtime_config.get("feature_weights", {})


        # 初始化結果容器與狀態指標
        info = {
            "status": "processing",  
            "message": ""
        }

        flat_features = []  # 存放結構: (欄位名稱, 語意查詢句, 原始關鍵字)
        task_weights = []

        # 不分主次，直接遍歷所有 keywords 屬性，各自拉出獨立的向量通道
        for field_key, val_list in keywords.items():
            for item in val_list:
                # 確保拿掉前後空白
                clean_item = item.strip()
                if not clean_item: 
                    continue
                    
                feat_id = f"{field_key}_{clean_item}"
                
                # 🎯 關鍵調整：直接將「乾淨的單一關鍵字」作為語意查詢句（query_sentence）
                query_sentence = clean_item
                
                weight = llm_weights.get(feat_id, 1.0 / len(llm_weights) if llm_weights else 0.2)
                
                # 保持原本的 Tuple 三元組結構，讓後續的 encode 與 Qdrant 完美相容不崩潰
                flat_features.append((field_key, query_sentence, clean_item)) 
                task_weights.append(float(weight))

        num_semantic_dims = len(flat_features)
        
        # 關聯式資料庫的店家搜尋結果列表,準備要丟入向量進行範圍搜尋
        rdbms_ids = [row.get("id") for row in db_results] 

        # 將 db_results 轉成以 id 字串為 Key 的映射表，供後面精排引擎與 O(1) 快速查詢使用
        db_map = {str(row.get("id")): row for row in db_results}

        # 初始化店家的多維語意特徵空間字典: rid -> [Dim0_score, Dim1_score, ...]
        restaurant_features = {str(rid): [] for rid in rdbms_ids}

        # 判定活化 GPU 的指標直接對齊全域
        vector_needed = plan.get("vector_needed", False)

        # 分流處理
        if not vector_needed:
            logger.info(f"[Vector Service][SID: {s_id}] 本次無向量語意需求，跳過 GPU 與 Qdrant，進入純指標通道")
            best_score = 1.0
            CURRENT_THRESHOLD = 0.0
            
            # 💡 修正：為了讓 V2 精排引擎能正常並行矩陣運算，我們為其建立一組「虛擬特徵通道」
            # 這樣 flat_features 就不會是空列表，S_matrix 也不會維度爆炸
            flat_features = [("pure_sort", "純排序保底通道", "pure_sort")]
            task_weights = [1.0]
            logical_op = "OR"  # 平刷保底，不執行 AND 硬切
            
            # 將所有店家的特徵分數平刷為 1.0
            # 這樣既能 100% 安全挺過精排層的 HARD_THRESHOLD，又能把重排主導權完美還給 MySQL 指標！
            for rid in rdbms_ids:
                restaurant_features[str(rid)] = [1.0]
        else:
            # 將「多通路召回明細日誌」補回，清楚定格被查詢的向量屬性、關鍵字與處理句
            logger.info(f"[Vector Service][SID: {s_id}] ======= 啟動多通路語意招回通道 =======")
            logger.info(f"[Vector Service][SID: {s_id}] 總特徵維度數 (Num Channels): {num_semantic_dims}")
            
            for idx, (field_name, sentence, kw) in enumerate(flat_features):
                logger.info(f" ├── [通道 {idx}] 向量屬性欄位: '{field_name}' | 查詢關鍵字: '{kw}'")
                logger.info(f"      └── 空間投影描述句: \"{sentence}\"")
            logger.info(f" ===================================================================")
            
            # 性能壓測關鍵：利用 GPU Batch 向量化，多個維度的句子一次算完，只戳一次顯卡
            query_sentences = [feat[1] for feat in flat_features]
            query_vectors = self.model.encode(query_sentences, normalize_embeddings=True).tolist()

            q_start = time.perf_counter()


            # 遍歷每一路特徵通道，去 Qdrant 撈這 500 筆種子選手在各維度上的獨立得分
            for i, (feat_id, _, _) in enumerate(flat_features):
                vector_results = await self.repo.search_in_ids(
                    query_vector=query_vectors[i],
                    rdbms_ids=rdbms_ids
                )

                all_vector_results.extend(vector_results)
                
                # 將當前特徵路的相似度結果建立成快速映射表
                current_score_map = {str(v.id): float(v.score) for v in vector_results}
                for rid in rdbms_ids:
                    # 沒命中的店家給予 0.1 背景噪音保底值，防止後續 NumPy 進對數空間時遇到 0 崩潰
                    score = current_score_map.get(str(rid), 0.1)
                    restaurant_features[str(rid)].append(score)

            q_end = time.perf_counter()
            info["qdrant_time"] = q_end - q_start

            # 改用固定實體門檻（常數），不再呼叫動態門檻函式
            # 🟢 修正點一：門檻攔截層正式對齊全域邏輯閘
            FIXED_SEMANTIC_THRESHOLD = 0.20  
            CURRENT_THRESHOLD = FIXED_SEMANTIC_THRESHOLD
            
            # 橫向掃描：根據全域算符動態調變。AND 模式下，必須【每一路特徵】都突破門檻，才算及格！
            valid_restaurant_features = {}
            
            for rid, scores in restaurant_features.items():
                if not scores: continue
                
                if logical_op == "AND":
                    # AND 閘：必須所有特徵通道都 >= 0.40
                    is_qualified = all(score >= FIXED_SEMANTIC_THRESHOLD for score in scores)
                else:
                    # OR 閘：只要有一路特徵過門檻即可
                    is_qualified = any(score >= FIXED_SEMANTIC_THRESHOLD for score in scores)
                
                if is_qualified:
                    valid_restaurant_features[rid] = scores

            # 更新下一階段參與精排的特徵矩陣
            restaurant_features = valid_restaurant_features
            has_any_match = len(restaurant_features) > 0
            
            best_score = 1.0 if has_any_match else 0.0
            logger.info(f"[Vector Service][SID: {s_id}] 採用固定實體門檻: {CURRENT_THRESHOLD} | 算符: {logical_op} | 通過門檻店家數: {len(restaurant_features)}")


        # --- 統一門檻檢查（依據固定門檻篩選結果決策） ---
        if best_score < CURRENT_THRESHOLD:
            logger.warning(f"[Vector Service][SID: {s_id}] 候選店家的語意特徵全數低於固定門檻 {CURRENT_THRESHOLD}，拒絕招回。")
            info.update({
                "status": "vector_no_match", 
                "message": "抱歉，附近目前沒有找到符合您描述的店家。"
            })
            return [], info

        # --- 執行權重排序（對齊全新多迴路矩陣執行引擎） ---
        logger.info(f"[Vector Service][SID: {s_id}] 進入動態矩陣精排，候選店家數: {len(db_results)}")
        r_start = time.perf_counter()
        
        # =========================================================================
        # 🧪 【精排引擎 A/B 測試切換開關】 
        # 解開你想測試的版本註解，並把另一個版本註解掉即可。
        # =========================================================================
        
        # 👉 【版本一：V1 傳統極值調和版】（保留黑馬、點積對數平滑）
        # logger.info(f"[Vector Service][SID: {s_id}] 運行模式：_apply_hybrid_ranking_v1")
        # final_results = await self._apply_hybrid_ranking_v1(
        #     db_map=db_map,                 
        #     flat_features=flat_features,   
        #     matrix_data=restaurant_features, 
        #     keywords=keywords,
        #     plan=plan,
        #     logical_op=logical_op,            
        #     task_weights=task_weights,
        #     vector_results=all_vector_results         
        # )

        # 👉 【版本二：V2 動態矩陣門控過濾版】（支援複雜邏輯字串、硬門檻過濾不符者）
        logger.info(f"[Vector Service][SID: {s_id}] 運行模式：_apply_hybrid_ranking_v2")
        final_results = await self._apply_hybrid_ranking_v2(
            db_map=db_map,                 
            flat_features=flat_features,   
            matrix_data=restaurant_features, 
            keywords=keywords,
            plan=plan,
            logical_op=logical_op,            
            task_weights=task_weights,
            vector_results=all_vector_results,
            logic_threshold=kwargs.get('logic_threshold', 0.15)# 傳入 V2 特有的過濾硬門檻
        )
        
        r_end = time.perf_counter()
        info.update({
            "status": "completed",
            "ranking_time": round(r_end - r_start, 4),
            "message": f"搜尋成功：已從 {len(db_results)} 筆候選店家中篩選出 {len(final_results)} 筆最佳結果。"
        })
        
        return final_results, info

    
    
    # 根據向量查詢結果進行權重運算與排序
    # 為什麼移除 top_k 截斷：現在由 Route 層搭配 Redis 分頁快取處理截斷，
    # 此方法負責回傳所有通過語意門檻的店家，確保分頁能存取完整排序結果
    # async def _apply_hybrid_ranking_v1(
    #     self,
    #     db_map: Dict[str, Any],         
    #     flat_features: List[Tuple[str, str, str]],  
    #     matrix_data: Dict[str, List[float]], 
    #     keywords: Dict[str, Any],
    #     plan: Dict[str, Any],
    #     logical_op: str,                 
    #     task_weights: List[float],       
    #     **kwargs                         
    # ) -> List[Dict[str, Any]]:

    #     s_id = plan.get("s_id", "unknown")

    #     # LLM 有時候會給一些垃圾標籤，這邊先擋掉以免後面崩潰
    #     sort_conditions = plan.get("sort_conditions", [])

    #     # Filter out trash tags
    #     valid_conditions = [
    #         cond.get("field") for cond in sort_conditions 
    #         if isinstance(cond, dict) and cond.get("field") in RankSettings.ALLOWED_FIELDS
    #     ]


    #     if not valid_conditions:
    #         weights = RankSettings.DEFAULT_WEIGHTS.copy()
    #         sort_strategy = "預設語意優先"
    #     else:
    #         weights = RankSettings.DYNAMIC_BASE.copy()
    #         sort_strategy = f"條件排序 ({', '.join(valid_conditions)})"
            
    #         # 動態分配累加
    #         # the competition
    #         for idx, field in enumerate(valid_conditions):
    #             bonus = RankSettings.PRIMARY_BONUS if idx == 0 else RankSettings.SECONDARY_BONUS
    #             weights[field] = weights.get(field, 0.0) + bonus

    #     # 總和必須是 1，不然 NumPy 的 exp 會算到起飛
    #     total_w = sum(weights.values())
    #     if total_w > 0:
    #         # 因為 round(..., 2) 有時候會讓總和變成 0.99 或 1.01。雖然對 np.exp 影響不大，
    #         # 為了數據純淨把round(...,2)拿掉
    #         weights = {k: v / total_w for k, v in weights.items()}
    #     else:
    #         weights = RankSettings.DEFAULT_WEIGHTS.copy()

    #     logger.info(f"[Hybrid Rank][SID: {s_id}] 採用策略: {sort_strategy}, 最終權重分配: {weights}")


    #     # 準備矩陣與數據
    #     valid_ids = []
    #     data_list = []

    #     # 🟢 核心重構：從 kwargs 中安全攔截原始的 Qdrant 招回 DTO 清單（如果有的話）
    #     # 並建立一組 rid -> review_summary 的快速過渡映射表
    #     raw_vector_results = kwargs.get("vector_results", [])
    #     summary_map = {}
    #     if raw_vector_results:
    #         summary_map = {str(v.id): v.review_summary for v in raw_vector_results if hasattr(v, 'review_summary')}
        
    #     all_counts = [row.get('user_ratings_total', 0) for row in db_map.values()]
    #     max_reviews_log = math.log1p(max(all_counts)) if all_counts and max(all_counts) > 0 else 1.0


    #     # 拿外層好不容易傳進來的指揮官 logical_op 與 user_location 正式對撞物理現實
    #     for v_id, scores in matrix_data.items():
    #         if v_id in db_map:
    #             store = db_map[v_id]
                
    #             if logical_op == "AND":
    #                 # 🚀 執行我們上一輪講的極值調和公式（抗稀釋）
    #                 max_score = float(np.max(scores)) if scores else 0.1
    #                 avg_score = float(np.average(scores, weights=task_weights)) if scores else 0.1
                    
    #                 hit_count = sum(1 for s in scores if s >= 0.40)
    #                 hit_ratio = hit_count / len(scores) if scores else 0.0
                    
    #                 similarity_score = (max_score * 0.5) + (avg_score * 0.5) + (hit_ratio * 0.15)
    #             else:
    #                 # OR 閘
    #                 mask = np.array([1.0 if s >= 0.40 else 0.0 for s in scores])
    #                 similarity_score = float(np.sum(np.array(task_weights) * mask)) if scores else 0.1
                    
    #             rating_score = float(store.get('rating', 0)) / 5.0  
    #             popularity_score = math.log1p(store.get('user_ratings_total', 0)) / max_reviews_log 
                
    #             # 2. 空間抗噪生死門：檢驗 user_location 是否有合法的物理經緯度
    #             user_loc = plan.get("user_location")
    #             if user_loc and user_loc.get("lat") is not None and user_loc.get("lng") is not None:
    #                 dist_m = float(store.get("distance", 0))    
    #                 distance_score = 1.0 / (1.0 + (dist_m / 1000.0))    
    #             else:
    #                 # 使用者沒開附近查詢：強制將距離分數平刷為 1.0
    #                 # 因為 log(1.0) = 0，在對數點積中距離噪音會被物理性100%抹殺！
    #                 distance_score = 1.0

    #             data_list.append([similarity_score, rating_score, popularity_score, distance_score]) 
    #             valid_ids.append(v_id)

    #     if len(data_list) == 0:
    #         logger.error(f"[Rank] SID:{s_id} 沒資料可以排!檢查一下 SQL 或向量庫。")
    #         return []

    #     # 把dist_list轉成numpy矩陣,也為了數據的純淨性
    #     # 根據用戶需求決定的權重封裝成一個長度為 4 的向量。如: w = [w_{sim}, w_{rating}, w_{pop}, w_{dist}]
    #     matrix = np.array(data_list) 
    #     weights_vec = np.array([
    #         weights["similarity"], 
    #         weights["rating"], 
    #         weights["popularity"], 
    #         weights["distance"]
    #     ])
        

    #     eps = 1e-6 # 這是為了防止對數運算遇到 0 崩潰加的保險
        
    #     # 核心運算：對數空間點積
    #     # 為了將線性空間的特徵值映射到對數流形 (Log-manifold)
    #     log_matrix = np.log(matrix + eps)
        
    #     # 不直接做 dot，而是用元素相乘 (Element-wise multiplication)
    #     # 這樣會得到一個 N x 4 的矩陣，裡面存著每個店家的每個維度實際加了多少分
    #     contribution_matrix = log_matrix * weights_vec
        
    #     # 總分依然是橫向加總
    #     total_log_scores = np.sum(contribution_matrix, axis=1)
        
    #     # 為了實現非線性的幾何聚合 (Non-linear Geometric Aggregation)
    #     # 沒有以下這一行其實只是換成矩陣運算的線性加權(跟之前的版本是一樣的效果)
    #     final_scores = np.exp(total_log_scores)  # 為了實現非線性的幾何聚合 (Non-linear Geometric Aggregation)
    #     seen_names = set() # 用於追蹤已排入的店名

    #     # 理由提取與結果封裝
    #     sorted_indices = np.argsort(final_scores)[::-1]
    #     final_results = []
    #     for idx in sorted_indices:
    #         v_id = valid_ids[idx]

    #         sim_score = matrix[idx][0]
    #         if sim_score < kwargs.get('semantic_threshold', 0.40):
    #             logger.debug(f"[Hybrid Rank] ID: {v_id} 語意分數 {sim_score:.4f} 不及格，直接淘汰。")
    #             continue # 跳過這家店，不加入推薦名單！
            
    #         store_entry = db_map[v_id].copy()

    #         raw_tags = store_entry.get("facility_tags")

    #         # logger.info(f"[DEBUG] ID:{v_id} 原始 raw_tags 型態: {type(raw_tags)} 內容: {raw_tags}")

    #         if raw_tags:
    #             if isinstance(raw_tags, str):
    #                 try:
    #                     # 必須把解析後的結果「指定回」字典
    #                     store_entry["facility_tags"] = json.loads(raw_tags)
    #                 except:
    #                     # 解析失敗時，保留原始字串供除錯，或設為空列表
    #                     store_entry["facility_tags"] = [] 
    #             # 如果已經是 list 就維持原樣
    #         else:
    #             # 如果 raw_tags 是 None 或空字串
    #             store_entry["facility_tags"] = []

    #         if v_id in summary_map and summary_map[v_id]:
    #             store_entry["review_summary"] = summary_map[v_id]
    #         else:
    #             # 保底防禦：如果 Qdrant 沒撈到，就看資料庫有沒有，都沒有就給予保底提示文字，防止 Pipeline 斷裂
    #             store_entry["review_summary"] = store_entry.get("review_summary", "暫無精選評論摘要")

    #         name = store_entry.get("restaurant_name")

    #         # 如果這家店名已經出現過了，就跳過 (因為目前的 idx 是由高分排到低分，先入者必為最高分)
    #         if name in seen_names:
    #             continue
                
    #         # 找出這家店得分最高的維度索引
            
    #         # 把權重為 0.0 的維度，分數設為極小的負數 (-999.0)，讓它絕對不可能成為最大值
    #         #for i, w in enumerate(weights_vec):
    #         #    if w == 0.0:
    #         #        masked_contribution[i] = -999.0 
            


    #         # 全特徵狀態對撞可解釋性理由生成引擎

    #         matched_features = []    
    #         unmatched_features = []  
            
    #         # 1. 實時解耦多通道語意特徵與分數
    #         # 實時解耦多通道語意特徵與分數
    #         if flat_features and scores:
    #             for idx_dim, (field_key, _, item) in enumerate(flat_features):
    #                 channel_score = scores[idx_dim]
                    
    #                 # 把 channel_score 用自然語言格式化，塞進每一路特徵的屁股後面！
    #                 if channel_score >= 0.40:
    #                     if field_key == "service_tags":
    #                         matched_features.append(f"有{item}(分:{channel_score:.2f})")
    #                     elif field_key == "cuisine":
    #                         matched_features.append(f"符合{item}風格(分:{channel_score:.2f})")
    #                     elif field_key == "food_type":
    #                         matched_features.append(f"主營{item}(分:{channel_score:.2f})")
    #                 else:
    #                     if field_key == "service_tags":
    #                         unmatched_features.append(f"無{item}(分:{channel_score:.2f})")
    #                     elif field_key == "cuisine":
    #                         unmatched_features.append(f"非{item}風格(分:{channel_score:.2f})")
    #                     elif field_key == "food_type":
    #                         unmatched_features.append(f"缺{item}(分:{channel_score:.2f})")

    #         # 2. 從實時精排 matrix 中拉出其他參與排序的幾何硬指標
    #         sim_val = float(matrix[idx][0])
    #         r_val   = float(matrix[idx][1]) * 5.0  # 還原回 5 星制
    #         p_val   = float(matrix[idx][2])        # 歸一化人氣分 (0.0 ~ 1.0)
    #         d_val   = float(matrix[idx][3])        # 歸一化距離分 (0.0 ~ 1.0)

    #         # 3. 判定幾何指標的自然語言狀態與分數回傳
    #         geo_status_list = [f"語意匹配:{sim_val:.2f}"]
            
    #         # 只要該欄位在權重分配中大於 0 (代表有參與本次排序戰場)
    #         if weights["rating"] > 0:
    #             geo_status_list.append(f"店家評分:{r_val:.1f}星")
    #         if weights["popularity"] > 0:
    #             # 根據歸一化區間貼心分類，並附帶分數
    #             pop_desc = "人氣爆棚" if p_val >= 0.85 else ("人氣頗高" if p_val >= 0.50 else "客群穩定")
    #             geo_status_list.append(f"{pop_desc}({p_val:.2f})")
    #         if weights["distance"] > 0 and plan.get("distance_needed"):
    #             dist_desc = "距離極近" if d_val >= 0.85 else ("距離適中" if d_val >= 0.50 else "距離稍遠")
    #             geo_status_list.append(f"{dist_desc}({d_val:.2f})")

    #         # 4. 語意基本匹配等級
    #         if sim_val >= 0.60:
    #             base_status = "高度符合期待"
    #         elif sim_val >= 0.45:
    #             base_status = "語意大致符合"
    #         else:
    #             base_status = "部分特徵相關"

    #         # 5. 鋼鐵語意邏輯拼裝鏈 (將符合、不符合、排序指標串聯)
    #         match_str = f"【符合】{', '.join(matched_features)}" if matched_features else ""
    #         unmatch_str = f"【不符合】{', '.join(unmatched_features)}" if unmatched_features else ""
    #         geo_str = f"【排序權重指標】{', '.join(geo_status_list)}"
            
    #         # 把所有存在的部件用半形分號完美串聯
    #         detail_parts = [p for p in [match_str, unmatch_str, geo_str] if p]
            
    #         if not plan.get("vector_needed", False):
    #             final_reason = f"依據硬指標最佳推薦（{'; '.join(detail_parts)}）"
    #         else:
    #             final_reason = f"{base_status}（{'; '.join(detail_parts)}）"

    #         store_entry["ranking_reason"] = final_reason

    #         # =================================================================


    #         store_entry["applied_strategy"] = sort_strategy
    #         store_entry["hybrid_score"] = round(float(final_scores[idx]), 4)
    #         store_entry["semantic_similarity"] = round(matrix[idx][0], 4)
            
    #         store_entry["score_analysis"] = {
    #             "similarity": round(matrix[idx][0], 2),
    #             "rating": round(matrix[idx][1], 2),
    #             "popularity": round(matrix[idx][2], 2),
    #             "distance": round(matrix[idx][3], 2)
    #         }
            
    #         final_results.append(store_entry)
    #         seen_names.add(name)  # 標記此店名已處理

    #         # 為什麼移除 top_k break：
    #         # 分頁需要完整的排序結果存入 Redis，由 Route 層的 SearchSessionCache 負責切頁。
    #         # 不再在此截斷，確保所有通過門檻的店家都被保留。

    #     logger.info(f"[Hybrid Rank][SID: {s_id}] 排序完成，已生成可解釋性理由。")
    #     return final_results
    
    async def _apply_hybrid_ranking_v2(
        self,
        db_map: Dict[str, Any],         
        flat_features: List[Tuple[str, str, str]],  
        matrix_data: Dict[str, List[float]], 
        keywords: Dict[str, Any],
        plan: Dict[str, Any],
        logical_op: str,  # 這裡也可以直接傳入你的動態邏輯字串，例如 "(0 AND 1) AND (NOT 2)"
        task_weights: List[float],       
        **kwargs                         
    ) -> List[Dict[str, Any]]:

        s_id = plan.get("s_id", "unknown")
        sort_conditions = plan.get("sort_conditions", [])

        # Filter out trash tags
        valid_conditions = [
            cond.get("field") for cond in sort_conditions 
            if isinstance(cond, dict) and cond.get("field") in RankSettings.ALLOWED_FIELDS
        ]

        if not valid_conditions:
            weights = RankSettings.DEFAULT_WEIGHTS.copy()
            sort_strategy = "預設語意優先"
        else:
            weights = RankSettings.DYNAMIC_BASE.copy()
            sort_strategy = f"條件排序 ({', '.join(valid_conditions)})"
            
            for idx, field in enumerate(valid_conditions):
                bonus = RankSettings.PRIMARY_BONUS if idx == 0 else RankSettings.SECONDARY_BONUS
                weights[field] = weights.get(field, 0.0) + bonus

        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}
        else:
            weights = RankSettings.DEFAULT_WEIGHTS.copy()

        logger.info(f"[Hybrid Rank][SID: {s_id}] 採用策略: {sort_strategy}, 最終權重分配: {weights}")

        # 🟢 核心重構第一步：將所有多通道 scores 組裝成整張大矩陣，進行並行邏輯閘運算
        # 這樣做可以完全抽離硬編碼的 AND / OR，支援任意複雜的邏輯搭配
        v_ids_order = [v_id for v_id in matrix_data.keys() if v_id in db_map]
        if not v_ids_order:
            logger.error(f"[Rank] SID:{s_id} 沒資料可以排! 檢查一下 SQL 或向量庫。")
            return []

        # 建立大相似度矩陣 (N x M)
        S_matrix = np.array([matrix_data[v_id] for v_id in v_ids_order])

        # 軟化激活函數 (過濾前的平滑飽和)
        def _soft_gate(similarity, threshold=0.5, steepness=12, epsilon=0.01):
            activated = 1.0 / (1.0 + np.exp(-steepness * (similarity - threshold)))
            return np.maximum(activated, epsilon)

        G_list = []
        for idx_dim, (field_key, _, item) in enumerate(flat_features):
            channel_scores = S_matrix[:, idx_dim]
            
            if field_key == "cuisine":
                # 📌 菜系是硬需求！把陡峭度從 12 飆到 25，門檻拉高到 0.50
                # 這樣 0.4 左右的擦邊日式料理會瞬間暴跌趨近於 0，在後續 HARD_THRESHOLD 直接被蒸發
                activated = 1.0 / (1.0 + np.exp(-25 * (channel_scores - 0.50)))
            else:
                # 一般標籤維持原樣
                activated = 1.0 / (1.0 + np.exp(-12 * (channel_scores - 0.40)))
                
            G_list.append(np.maximum(activated, 0.01))

        G_matrix = np.column_stack(G_list)

        # 動態邏輯閘解析器
        # 動態邏輯閘解析器
        def _evaluate_logic(expr_str, G_mat, S_mat):
            expr = expr_str.upper()
            expr = re.sub(r'\b(\d+)\b', r'G_mat[:, \1]', expr)
            expr = re.compile(r'NOT\s+([A-Za-z0-9_:.\[\]\,\s]+)').sub(r'(1.0 - \1)', expr)
            expr = expr.replace('AND', '*')
            expr = expr.replace('OR', '+')
            try:
                # 💡 修正點：傳入 {"__builtins__": None} 安全封鎖內建函式，並加上 np.clip 限制最低點，防止 log 負分爆炸
                raw_gate = eval(expr, {"G_mat": G_mat, "S_mat": S_mat, "np": np, "__builtins__": None})
                return np.clip(raw_gate, 0.001, 1.0)
            except Exception as e:
                # 保底降級
                if "AND" in expr_str:
                    return np.clip(np.prod(G_mat, axis=1), 0.001, 1.0)
                else:
                    return np.clip(np.sum(G_mat * task_weights, axis=1), 0.001, 1.0)

        # 這裡 logical_op 變數直接升格：可以接字串 "(0 AND 1) AND (NOT 2)"，也可以接傳統的 "AND"/"OR"
        gate_mask_vector = _evaluate_logic(logical_op, G_matrix, S_matrix)

        # 設定硬性生死門過濾門檻（邏輯得分低於此門檻的店直接在排序前人間蒸發）
        HARD_THRESHOLD = kwargs.get('logic_threshold', 0.30)

        # 準備矩陣與數據
        valid_ids = []
        data_list = []
        final_gate_masks = [] # 追蹤留下來的店家的邏輯閘分數
        
        raw_vector_results = kwargs.get("vector_results", [])
        summary_map = {}
        if raw_vector_results:
            summary_map = {str(v.id): v.review_summary for v in raw_vector_results if hasattr(v, 'review_summary')}
        
        all_counts = [row.get('user_ratings_total', 0) for row in db_map.values()]
        max_reviews_log = math.log1p(max(all_counts)) if all_counts and max(all_counts) > 0 else 1.0

        # 🟢 核心重構第二步：套用硬門檻過濾，不符邏輯直接剔除，杜絕雜訊進入對數流形
        for idx_mat, v_id in enumerate(v_ids_order):
            gate_score = float(gate_mask_vector[idx_mat])
            
            # 【硬門檻過濾關鍵】不符合邏輯的店家不用出來了，直接在此淘汰
            if gate_score < HARD_THRESHOLD:
                logger.debug(f"[Hybrid Rank] ID: {v_id} 邏輯閘分數 {gate_score:.4f} 低於門檻 {HARD_THRESHOLD}，拒絕輸出。")
                continue 

            store = db_map[v_id]
            scores = matrix_data[v_id]
            
            # 這時候相似度分數就等於完美融合了使用者 AND/OR 邏輯閘搭配後的綜合權重
            similarity_score = gate_score
                
            rating_score = float(store.get('rating', 0)) / 5.0  
            popularity_score = math.log1p(store.get('user_ratings_total', 0)) / max_reviews_log 
            
            user_loc = plan.get("user_location")
            if user_loc and user_loc.get("lat") is not None and user_loc.get("lng") is not None:
                dist_m = float(store.get("distance", 0))    
                distance_score = 1.0 / (1.0 + (dist_m / 1000.0))    
            else:
                distance_score = 1.0

            data_list.append([similarity_score, rating_score, popularity_score, distance_score]) 
            valid_ids.append(v_id)
            final_gate_masks.append(gate_score) # 存入通過者

        if len(data_list) == 0:
            logger.error(f"[Rank] SID:{s_id} 經過邏輯閘過濾後，沒有任何一家店符合條件！")
            return []

        # 轉成 numpy 矩陣
        matrix = np.array(data_list) 
        weights_vec = np.array([
            weights["similarity"], 
            weights["rating"], 
            weights["popularity"], 
            weights["distance"]
        ])
        
        # 💡 修正點：將 eps 微調至 1e-3
        # 這樣當店家通過純排序或邊緣通過邏輯閘時（分數如 0.3x），ln(0.3 + 0.001) 不會縮減成致命的極端負數，確保拓撲平滑度
        eps = 1e-3 
        
        # 進入你原本完美的對數空間點積與非線性幾何聚合
        log_matrix = np.log(matrix + eps)
        contribution_matrix = log_matrix * weights_vec
        total_log_scores = np.sum(contribution_matrix, axis=1)
        final_scores = np.exp(total_log_scores)
        
        seen_names = set() 

        # 理由提取與結果封裝
        sorted_indices = np.argsort(final_scores)[::-1]
        final_results = []
        for idx in sorted_indices:
            v_id = valid_ids[idx]
            store_entry = db_map[v_id].copy()
            scores = matrix_data[v_id] # 回頭去拿原本的多通道分數，用於理由生成

            raw_tags = store_entry.get("facility_tags")
            if raw_tags:
                if isinstance(raw_tags, str):
                    try:
                        store_entry["facility_tags"] = json.loads(raw_tags)
                    except:
                        store_entry["facility_tags"] = [] 
            else:
                store_entry["facility_tags"] = []

            if v_id in summary_map and summary_map[v_id]:
                store_entry["review_summary"] = summary_map[v_id]
            else:
                store_entry["review_summary"] = store_entry.get("review_summary", "暫無精選評論摘要")

            name = store_entry.get("restaurant_name")
            if name in seen_names:
                continue
                
            # 全特徵狀態對撞可解釋性理由生成
            matched_features = []    
            unmatched_features = []  
            
            if flat_features and scores:
                for idx_dim, (field_key, _, item) in enumerate(flat_features):
                    channel_score = scores[idx_dim]
                    if channel_score >= 0.40:
                        if field_key == "service_tags":
                            matched_features.append(f"有{item}(分:{channel_score:.2f})")
                        elif field_key == "cuisine":
                            matched_features.append(f"符合{item}風格(分:{channel_score:.2f})")
                        elif field_key == "food_type":
                            matched_features.append(f"主營{item}(分:{channel_score:.2f})")
                    else:
                        if field_key == "service_tags":
                            unmatched_features.append(f"無{item}(分:{channel_score:.2f})")
                        elif field_key == "cuisine":
                            unmatched_features.append(f"非{item}風格(分:{channel_score:.2f})")
                        elif field_key == "food_type":
                            unmatched_features.append(f"缺{item}(分:{channel_score:.2f})")

            sim_val = float(matrix[idx][0]) # 這裡對應的就是被邏輯閘加權/篩選後的分數了
            r_val   = float(matrix[idx][1]) * 5.0  
            p_val   = float(matrix[idx][2])        
            d_val   = float(matrix[idx][3])        

            geo_status_list = [f"邏輯門控複合分:{sim_val:.2f}"]
            
            if weights["rating"] > 0:
                geo_status_list.append(f"店家評分:{r_val:.1f}星")
            if weights["popularity"] > 0:
                pop_desc = "人氣爆棚" if p_val >= 0.85 else ("人氣頗高" if p_val >= 0.50 else "客群穩定")
                geo_status_list.append(f"{pop_desc}({p_val:.2f})")
            if weights["distance"] > 0 and plan.get("distance_needed"):
                dist_desc = "距離極近" if d_val >= 0.85 else ("距離適中" if d_val >= 0.50 else "距離稍遠")
                geo_status_list.append(f"{dist_desc}({d_val:.2f})")

            if sim_val >= 0.60:
                base_status = "高度符合期待"
            elif sim_val >= 0.45:
                base_status = "語意大致符合"
            else:
                base_status = "部分特徵相關"

            match_str = f"【符合】{', '.join(matched_features)}" if matched_features else ""
            unmatch_str = f"【不符合】{', '.join(unmatched_features)}" if unmatched_features else ""
            geo_str = f"【排序權重指標】{', '.join(geo_status_list)}"
            
            detail_parts = [p for p in [match_str, unmatch_str, geo_str] if p]
            
            if not plan.get("vector_needed", False):
                final_reason = f"依據硬指標最佳推薦（（{'; '.join(detail_parts)}）"
            else:
                final_reason = f"{base_status}（{'; '.join(detail_parts)}）"

            store_entry["ranking_reason"] = final_reason

            store_entry["applied_strategy"] = sort_strategy
            store_entry["hybrid_score"] = round(float(final_scores[idx]), 4)
            store_entry["semantic_similarity"] = round(final_gate_masks[idx], 4) # 寫回邏輯閘分數
            
            store_entry["score_analysis"] = {
                "similarity": round(matrix[idx][0], 2),
                "rating": round(matrix[idx][1], 2),
                "popularity": round(matrix[idx][2], 2),
                "distance": round(matrix[idx][3], 2)
            }
            
            final_results.append(store_entry)
            seen_names.add(name)  

        logger.info(f"[Hybrid Rank][SID: {s_id}] 排序與硬性邏輯過濾完成，已剔除不符條件之店家。")
        return final_results


if __name__ == "__main__":
    import asyncio

    async def test_run():
        service = VectorService()
        
        # 1. 模擬資料庫撈出來的店家 (RDBMS Results)
        mock_db_results = [
            {"id": 1, "restaurant_name": "老王拉麵", "rating": 4.5, "user_ratings_total": 1000, "distance": 500},
            {"id": 2, "restaurant_name": "小李便當", "rating": 3.2, "user_ratings_total": 50, "distance": 100},
            {"id": 3, "restaurant_name": "極黑和牛燒肉", "rating": 4.8, "user_ratings_total": 500, "distance": 2000},
        ]
        
        # 2. 模擬 LLM 產生的計畫 (Plan)
        # 測試場景：使用者想要「距離優先」
        mock_plan = {
            "s_id": "test_001",
            "vector_keywords": {
                "cuisine_type": "日式",
                "service_tags": "有停車場、冷氣"
            },
            "sort_conditions": [
                {"field": "distance", "direction": "asc"},
                {"field": "rating", "direction": "desc"}
            ]
        }

        print("\n🚀 [開始測試] 模擬搜尋與混合排序邏輯...")
        
        # 執行測試
        # 注意：因為測試環境沒接真的 VectorDB，你的 repo.search_in_ids 可能會報錯
        # 建議測試時可以先將 search_in_ids 內容暫時 mock 掉，或確保連線正常。
        try:
            results, info = await service.search_and_rank(
                db_results=mock_db_results,
                plan=mock_plan
            )

            print("\n✅ [排序結果回傳]")
            for i, r in enumerate(results):
                print(f"第 {i+1} 名: {r['restaurant_name']} | "
                      f"理由: {r['ranking_reason']} | "
                      f"總分: {r['hybrid_score']} | "
                      f"距離: {r['score_analysis']['distance']}")
            
            print(f"\n📊 [權重分配檢查]: {info.get('status')}")

        except Exception as e:
            print(f"❌ 測試失敗: {e}")
            print("提示：如果報錯是在 repo.search_in_ids，代表你可能沒開 Qdrant 或連不到 DB。")

    # 啟動非同步測試迴圈
    asyncio.run(test_run())