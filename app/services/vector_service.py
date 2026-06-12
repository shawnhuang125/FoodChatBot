from typing import List, Dict, Any, Optional, Tuple
from app.repository.vector_repository import VectorRepository
from sentence_transformers import SentenceTransformer
from app.models.search_dto import VectorSearchResult
from huggingface_hub import snapshot_download
import numpy as np
import math
import time
import json
import os
import re
from app.utils.app_logger import logger

class RankSettings:
    ALLOWED_FIELDS = {"distance", "rating", "popularity", "similarity"}
    DEFAULT_WEIGHTS = {
        "similarity": 0.50,
        "rating": 0.25,
        "popularity": 0.15,
        "distance": 0.10
    }
    DYNAMIC_BASE = {
        "similarity": 0.20,
        "rating": 0.10,
        "popularity": 0.10,
        "distance": 0.10
    }


class VectorService:
    def __init__(self):
        self.model_name = "BAAI/bge-m3"
        base_dir = os.getcwd() 
        self.model_path = os.path.abspath(os.path.join(base_dir, "models", "bge_m3"))
        
        if not os.path.exists(os.path.join(self.model_path, "config.json")):
            logger.info(f"模型檔案不完整，準備下載至 {self.model_path}...")
            os.makedirs(self.model_path, exist_ok=True) 
            snapshot_download(
                repo_id=self.model_name,
                local_dir=self.model_path,
                local_dir_use_symlinks=False  
            )
        
        logger.info(f"正在從 {self.model_path} 載入 BGE-M3 嵌入模型...")
        self.model = SentenceTransformer(self.model_path) 
        self.model.to('cuda') 
        logger.info("模型載入完成")
        self.repo = VectorRepository()

    async def search_and_rank(
        self,
        db_results: List[Dict[str, Any]],
        plan: Dict[str, Any],
        total_count: int = 0,
        **kwargs
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        
        r_start = time.perf_counter()
        all_vector_results = []
        s_id = plan.get("s_id", "unknown_sid")

        keywords = plan.get("vector_keywords", {})
        runtime_config = plan.get("matrix_runtime_config", {})
        logical_op = runtime_config.get("op", "AND").upper() 
        llm_weights = runtime_config.get("feature_weights", {})

        info = {"status": "processing", "message": ""}
        flat_features = []  
        task_weights = []

        # 1. 抽取語意特徵
        for field_key, val_list in keywords.items():
            if not isinstance(val_list, list):
                val_list = [val_list]
            for item in val_list:
                clean_item = str(item).strip()
                if not clean_item: 
                    continue
                    
                # 🟢 補回關鍵行：宣告特徵 ID，供下方權重對齊使用
                feat_id = f"{field_key}_{clean_item}"
                
                if field_key == "cuisine":
                    query_sentence = f"主打菜系為{clean_item}風味的餐廳"
                elif field_key == "food_type":
                    # 🟢 核心微調：引入語意擴展，將單字與店面詞、食物詞自然融合成一個強特徵矩陣
                    # 這樣當 clean_item 是 "麵" 時，會變成：包含麵食、麵條、麵店、麵點的餐飲小吃餐廳
                    # 完美涵蓋所有 BGE-M3 可能對齊的詞頻，徹底解決單字語意塌陷！
                    if len(clean_item) == 1:  # 針對像 "麵"、"飯" 這種單字做特殊語意加強
                        query_sentence = f"主打{clean_item}食、{clean_item}類、{clean_item}店的餐飲餐廳與小吃攤"
                    else:
                        query_sentence = f"主打食物種類為{clean_item}、{clean_item}料理的餐飲餐廳"
                        
                elif field_key in ["service_tags", "facility_tags"]:
                    query_sentence = f"有提供{clean_item}的所有餐廳"
                else:
                    query_sentence = clean_item
                
                weight = llm_weights.get(feat_id, 1.0 / len(llm_weights) if llm_weights else 0.2)
                flat_features.append((field_key, query_sentence, clean_item)) 
                task_weights.append(float(weight))



        num_semantic_dims = len(flat_features)
        rdbms_ids = [row.get("id") for row in db_results] 
        db_map = {str(row.get("id")): row for row in db_results}
        
        # 徹底斷絕 1.0 灌水殘留，未命中的底分一律就是 0.0 背景噪音，
        # 確保相似度回傳的內容如果該家店沒有那就一定是0.0,讓底造維持乾淨
        restaurant_features = {str(rid): [] for rid in rdbms_ids}

        vector_needed = plan.get("vector_needed", False)
        if num_semantic_dims == 0:
            vector_needed = False

        if not vector_needed:
            logger.info(f"[Vector Service][SID: {s_id}] 無實質語意特徵維度，切換純指標保底")
            flat_features = [("pure_sort", "純排序保底通道", "pure_sort")]
            task_weights = [1.0]
            logical_op = "OR"  
            for rid in rdbms_ids:
                restaurant_features[str(rid)] = [1.0]

            # 利用計時器包裹，拉取 Qdrant 原始 Payload DTO 補齊評論摘要
            q_start = time.perf_counter()
            all_vector_results = await self.repo.get_dtos_by_ids(rdbms_ids=rdbms_ids)
            q_end = time.perf_counter()
            info["qdrant_time"] = q_end - q_start
            
        else:
            # 印出有幾個通道與各自的關鍵字資訊
            # flat_features 的結構是 (field_key, query_sentence, clean_item)
            channels_info = [
                f"[{feat[0]} -> 關鍵字: '{feat[2]}' (查詢句: '{feat[1]}')]" 
                for feat in flat_features
            ]
            logger.info(
                f"[Vector Service][SID: {s_id}] ======= 啟動多通路語意召回通道 ======="
                f"\n總共派發通道數: {num_semantic_dims} 個"
                f"\n詳細通道清單:\n" + "\n".join(channels_info)
            )

            query_sentences = [feat[1] for feat in flat_features]
            query_vectors = self.model.encode(query_sentences, normalize_embeddings=True).tolist()

            q_start = time.perf_counter()
            for i, (f_key, _, _) in enumerate(flat_features):
                vector_results = await self.repo.search_in_ids(
                    query_vector=query_vectors[i],
                    rdbms_ids=rdbms_ids
                )
                all_vector_results.extend(vector_results)

                
                current_score_map = {str(v.id): float(v.score) for v in vector_results}
                for rid in rdbms_ids:
                    # 💡 沒戳到 Qdrant 的人，鐵律給予 0.0，杜絕高分污染
                    raw_score = current_score_map.get(str(rid), 0.0)

                    # =================================================================
                    # 🟢 核心修改：菜系/食物種類特徵的「軟性局部屏蔽 (Soft Masking)」
                    # =================================================================
                    # 設定一個寬鬆的特徵噪音臨界值。大於它代表「語意高度相關」(如 日本料理 與 日式料理)
                    # 小於它代表「基本上是跨菜系的語意塌陷雜訊」(如 搜尋義式 卻撈到 壽司)
                    if f_key in ["cuisine", "food_type"]:
                        # 0.68 是一個完美的軟隔離線，能包容同義詞，但能切斷完全無關的日義跨界污染
                        score = float(raw_score) if float(raw_score) >= 0.68 else 0.0
                    else:
                        score = float(raw_score)

                    restaurant_features[str(rid)].append(score)

            q_end = time.perf_counter()
            info["qdrant_time"] = q_end - q_start

        final_results = await self._apply_hybrid_ranking_v2(
            db_map=db_map,                 
            flat_features=flat_features,   
            matrix_data=restaurant_features, 
            plan=plan,           
            task_weights=task_weights,
            vector_results=all_vector_results,
            logic_threshold=kwargs.get('logic_threshold', 0.60)  
        )
        
        r_end = time.perf_counter()
        info.update({
            "status": "completed",
            "updated_total_count": len(final_results),
            "ranking_time": round(r_end - r_start, 4),
            "message": f"搜尋成功：已篩選出 {len(final_results)} 筆結果。"
        })
        return final_results, info
    


    async def _apply_hybrid_ranking_v2(
        self,
        db_map: Dict[str, Any],         
        flat_features: List[Tuple[str, str, str]],  
        matrix_data: Dict[str, List[float]], 
        plan: Dict[str, Any],        
        task_weights: List[float],       
        **kwargs                         
    ) -> List[Dict[str, Any]]:

        s_id = plan.get("s_id", "unknown")
        sort_conditions = plan.get("sort_conditions", [])

        # 🟢 補上這兩行，直接終結 Pylance 報錯
        v_logic_tree = plan.get("matrix_runtime_config", {}).get("vector_logic_tree")
        main_intent_indices = [idx for idx, (field, _, _) in enumerate(flat_features) if field != "service_tags"]

       # 1. 動態權重分配
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
            
            # 幾何衰減機制
            start_bonus = 0.5   # 起始 Bonus 分數
            decay_factor = 0.5  # 幾何衰減係數 (每次減半)
            
            for idx, field in enumerate(valid_conditions):
                # 依據公式： bonus = start_bonus * (decay_factor ** idx)
                # idx = 0 -> 0.5
                # idx = 1 -> 0.25
                # idx = 2 -> 0.125
                bonus = start_bonus * (decay_factor ** idx)
                weights[field] = weights.get(field, 0.0) + bonus

        total_w = sum(weights.values())
        weights = {k: v / total_w for k, v in weights.items()} if total_w > 0 else RankSettings.DEFAULT_WEIGHTS.copy()

        logger.info(f"[精排大腦][SID: {s_id}] 權重分配完成。策略: {sort_strategy} | 歸一化權重: {weights}")

        v_ids_order = [v_id for v_id in matrix_data.keys() if v_id in db_map]
        if not v_ids_order:
            return []

        raw_vector_results = kwargs.get("vector_results", [])
        # 改用防禦性 for 迴圈組裝映射表，防止多通道全量召回時空字串覆蓋有效數據
        summary_map = {}
        for v in raw_vector_results:
            v_id_str = str(v.id)
            v_summary = getattr(v, "review_summary", "") or ""
            
            # 只有當這家餐廳還沒存過摘要，或者新拿到的摘要長度大於原本存的長度，才允許寫入/更新
            if v_id_str not in summary_map or len(v_summary) > len(summary_map[v_id_str]):
                # 確保存進去的不是純空格或預設的無內容字串
                if v_summary.strip() and v_summary != "暫無精選評論摘要":
                    summary_map[v_id_str] = v_summary
        
        all_counts = [row.get('user_ratings_total', 0) for row in db_map.values()]
        max_reviews_log = math.log1p(max(all_counts)) if all_counts and max(all_counts) > 0 else 1.0

        # 組裝真實相似度矩陣 (N x M)
        S_matrix = np.array([matrix_data[v_id] for v_id in v_ids_order])
        HARD_THRESHOLD = kwargs.get('logic_threshold', 0.60)

        # 解析全域 MUST 強制名單
        must_constraints = {}
        logic_tree = plan.get("logic_tree", {})
        def _extract_must_rules(node):
            if not node or not isinstance(node, dict): return
            if node.get("constraint_level") == "MUST" and node.get("field") and node.get("value"):
                field = node["field"]
                if field not in must_constraints: must_constraints[field] = []
                must_constraints[field].extend([str(v).strip() for v in node["value"] if v])
            for sub_cond in node.get("conditions", []): _extract_must_rules(sub_cond)
        _extract_must_rules(logic_tree)


        # =================================================================
        # 🟢 階段一：精準向量邏輯閘過濾 (替換原本 _evaluate_logic 舊代碼)
        # =================================================================
        if v_logic_tree and S_matrix.size > 0:
            feat_to_idx = {(feat[0], feat[2]): idx for idx, feat in enumerate(flat_features)}

            def evaluate_vector_tree(node: dict) -> np.ndarray:
                if "op" in node and "conditions" in node:
                    op_type = node.get("op", "AND").upper()
                    child_masks = [evaluate_vector_tree(child) for child in node["conditions"]]
                    
                    if not child_masks:
                        return np.ones(S_matrix.shape[0])
                        
                    stacked = np.column_stack(child_masks)
                    if op_type == "AND":
                        return np.all(stacked == 1.0, axis=1).astype(float)
                    elif op_type == "OR":
                        return np.any(stacked == 1.0, axis=1).astype(float)
                    else:
                        return np.all(stacked == 1.0, axis=1).astype(float)

                f_key = node.get("field")
                val_list = node.get("value", [])
                if not isinstance(val_list, list): 
                    val_list = [val_list]
                
                leaf_mask = np.zeros(S_matrix.shape[0])
                for item in val_list:
                    clean_item = str(item).strip()
                    idx_dim = feat_to_idx.get((f_key, clean_item))
                    
                    if idx_dim is not None:
                        scores_dim = S_matrix[:, idx_dim]
                        for idx_mat, _ in enumerate(v_ids_order):
                            v_score = scores_dim[idx_mat]
                            if v_score >= HARD_THRESHOLD and v_score > 0.0:
                                leaf_mask[idx_mat] = 1.0
                            elif f_key in ["cuisine", "food_type"] and v_score >= 0.65:
                                leaf_mask[idx_mat] = 1.0
                                
                return leaf_mask

            gate_mask_vector = evaluate_vector_tree(v_logic_tree)
        else:
            gate_mask_vector = np.ones(len(v_ids_order))

        failed_count = len(v_ids_order) - int(np.sum(gate_mask_vector))
        logger.info(f"[精排大腦][SID: {s_id}] 階段一精準向量邏輯閘過濾完成。總候選: {len(v_ids_order)} | 通過: {int(np.sum(gate_mask_vector))} | 被生死門硬攔截: {failed_count}")

        # ==========================================
        # 🟢 階段二：對剩下的店家用 service_tags 進行加權排序
        # ==========================================
        
        service_indices = [
            idx for idx, (field, _, _) in enumerate(flat_features) if field == "service_tags"
        ]

        qualified_stores = []

        for idx_mat, v_id in enumerate(v_ids_order):
            # 門口直接攔截：主意圖不符的，直接 Out！
            if gate_mask_vector[idx_mat] == 0.0:
                continue 

            store = db_map[v_id]
            scores = S_matrix[idx_mat]
            
            # 1. 核心主意圖分數計算 (基底語意分)
            if main_intent_indices:
                main_scores = [float(scores[idx]) for idx in main_intent_indices if idx < len(scores)]
                active_main_scores = [s for s in main_scores if s >= HARD_THRESHOLD]
                core_base_score = np.mean(active_main_scores) if active_main_scores else HARD_THRESHOLD
            else:
                core_base_score = HARD_THRESHOLD

            # 2. 服務標籤 (service_tags) 命中計數累加
            match_count = 0
            for idx_dim in service_indices:
                if idx_dim < len(scores):
                    _, _, item = flat_features[idx_dim]
                    v_score = float(scores[idx_dim])
                    db_val = str(store.get("service_tags", "") or "")
                    
                    is_string_match = item in db_val if db_val else False
                    # 只要字串中招，或者 BGE-M3 向量算出來高於硬門檻，就算命中一項
                    if is_string_match or v_score >= HARD_THRESHOLD:
                        match_count += 1

            # 3. 實現「符合越多項排越前面」的軟性偏好加權機制
            soft_preference_modifier = 1.0
            if service_indices:
                if match_count > 0:
                    # 階梯式獎勵：每多一項符合，分數直接疊加額外紅利 (例如每項 +25%)
                    soft_preference_modifier *= (1.0 + 0.25 * match_count)
                else:
                    # 一項都沒符合的使用者指定服務，給予微幅扣分懲罰
                    soft_preference_modifier *= 0.90

            # 結合基底分與服務權重
            similarity_score = float(np.clip(core_base_score * soft_preference_modifier, 0.01, 2.0))

            # 存活下來的店家的日誌輸出
            if service_indices:
                logger.debug(
                    f"[精排大腦][SID: {s_id}] 店家 ID: {v_id} | 名稱: {store.get('restaurant_name')} "
                    f"| 主意圖底分: {core_base_score:.4f} | 服務標籤命中數: {match_count} "
                    f"| 軟偏好乘數: {soft_preference_modifier:.2f} -> 最終語意分: {similarity_score:.4f}"
                )
            
            # 其他硬指標分數歸一化
            rating_score = float(store.get('rating', 0)) / 5.0  
            popularity_score = math.log1p(store.get('user_ratings_total', 0)) / max_reviews_log 
            
            user_loc = plan.get("user_location")
            if user_loc and user_loc.get("lat") is not None and user_loc.get("lng") is not None:
                dist_m = float(store.get("distance", 0))    
                distance_score = 1.0 / (1.0 + (dist_m / 1000.0))    
            else:
                distance_score = 1.0

            store_entry = store.copy()
            store_entry["_geo_vector"] = [similarity_score, rating_score, popularity_score, distance_score]
            qualified_stores.append(store_entry)

        if not qualified_stores:
            return []

        # 3. 對數幾何重排 (多目標混排)
        matrix = np.array([s["_geo_vector"] for s in qualified_stores])
        weights_vec = np.array([weights["similarity"], weights["rating"], weights["popularity"], weights["distance"]])
        
        eps = 1e-3 
        log_matrix = np.log(matrix + eps)
        contribution_matrix = log_matrix * weights_vec
        total_log_scores = np.sum(contribution_matrix, axis=1)
        final_scores = np.exp(total_log_scores)

        for idx, store_entry in enumerate(qualified_stores):
            store_entry["hybrid_score"] = round(float(final_scores[idx]), 4)
            store_entry["semantic_similarity"] = round(matrix[idx][0], 4)

        qualified_stores.sort(key=lambda x: x["hybrid_score"], reverse=True)

        if qualified_stores:
            top_3 = [(s.get("restaurant_name"), s.get("hybrid_score")) for s in qualified_stores[:3]]
            logger.info(f"[精排大腦][SID: {s_id}] 終極幾何重排結束。進入理由包裝的店家數: {len(qualified_stores)} | 前三名預覽: {top_3}")


        # 最終去重與理由包裝 (現在只要一行)
        return self._package_final_results(
            qualified_stores=qualified_stores,
            matrix_data=matrix_data,
            flat_features=flat_features,
            must_constraints=must_constraints,
            summary_map=summary_map,
            weights=weights,
            plan=plan,
            sort_strategy=sort_strategy,
            hard_threshold=HARD_THRESHOLD
        )

    
    
    def _package_final_results(
        self,
        qualified_stores: List[Dict[str, Any]],
        matrix_data: Dict[str, List[float]],
        flat_features: List[Tuple[str, str, str]],
        must_constraints: Dict[str, List[str]],
        summary_map: Dict[str, str],
        weights: Dict[str, float],
        plan: Dict[str, Any],
        sort_strategy: str,
        hard_threshold: float
    ) -> List[Dict[str, Any]]:
        """
        將重排完畢的店家列表進行去重、評論摘要注入、特徵符合度比對，並包裝成最終輸出的資料格式。
        """
        seen_names = set()
        final_results = []
        
        for store_entry in qualified_stores:
            name = store_entry.get("restaurant_name")
            # 🛡️ 1. 餐廳名稱去重
            if name in seen_names: 
                continue
                
            v_id = str(store_entry.get("id"))
            scores = matrix_data.get(v_id, [0.0])
            
            # 複製一份資料避免改動到原始 reference
            store_entry = store_entry.copy()

            # 🛡️ 2. 注入精選評論摘要
            store_entry["review_summary"] = summary_map.get(v_id, store_entry.get("review_summary", "暫無精選評論摘要"))

            # 🛡️ 3. 設施標籤 facility_tags 反序列化與安全處理
            raw_tags = store_entry.get("facility_tags")
            if raw_tags and isinstance(raw_tags, str):
                try:
                    store_entry["facility_tags"] = json.loads(raw_tags)
                except:
                    store_entry["facility_tags"] = []
            else:
                store_entry["facility_tags"] = store_entry.get("facility_tags", [])

            # 🛡️ 4. 解析特徵符合/不符合狀況
            matched_features = []    
            unmatched_features = []  
            
            if flat_features and flat_features[0][0] != "pure_sort":
                for idx_dim, (field_key, _, item) in enumerate(flat_features):
                    if idx_dim < len(scores):
                        channel_score = scores[idx_dim]
                        db_val = str(store_entry.get(field_key, "") or "")
                        
                        # 判定符合標準
                        is_match = (channel_score >= hard_threshold)
                        if field_key in must_constraints:
                            is_match = is_match or any(kw in db_val for kw in must_constraints[field_key])
                        elif field_key == "service_tags":
                            is_match = is_match or (item in db_val if db_val else False)
                        
                        # 文字組裝
                        if is_match:
                            if field_key == "service_tags": matched_features.append(f"有{item}")
                            elif field_key == "cuisine": matched_features.append(f"符合{item}風格")
                            elif field_key == "food_type": matched_features.append(f"主營{item}")
                        else:
                            if field_key == "service_tags": unmatched_features.append(f"無{item}")
                            elif field_key == "cuisine": unmatched_features.append(f"非{item}風格")
                            elif field_key == "food_type": unmatched_features.append(f"缺{item}")

            # 🛡️ 5. 讀取並還原 _geo_vector 的標準化分數
            geo_vector = store_entry.get("_geo_vector", [0.0, 0.0, 0.0, 1.0])
            sim_val = geo_vector[0]
            r_val   = geo_vector[1] * 5.0
            p_val   = geo_vector[2]
            d_val   = geo_vector[3]

            # 🛡️ 6. 組裝排序權重指標文字
            geo_status_list = [f"語意匹配分:{sim_val:.2f}", f"店家評分:{r_val:.1f}星"]
            if weights.get("popularity", 0) > 0:
                geo_status_list.append("人氣爆棚" if p_val >= 0.85 else ("人氣頗高" if p_val >= 0.50 else "客群穩定"))
            if weights.get("distance", 0) > 0 and plan.get("distance_needed"):
                geo_status_list.append("距離極近" if d_val >= 0.85 else ("距離適中" if d_val >= 0.50 else "距離稍遠"))

            # 🛡️ 7. 拼裝終極理由文字（ranking_reason）
            base_status = "高度符合期待" if sim_val >= 0.55 else ("語意大致符合" if sim_val >= 0.45 else "部分特徵相關")
            match_str = f"【符合】{', '.join(matched_features)}" if matched_features else ""
            unmatch_str = f"【不符合】{', '.join(unmatched_features)}" if unmatched_features else ""
            geo_str = f"【排序權重指標】{', '.join(geo_status_list)}"
            
            detail_parts = [p for p in [match_str, unmatch_str, geo_str] if p]
            
            if flat_features[0][0] == "pure_sort":
                store_entry["ranking_reason"] = f"已為您篩選區域優質店家，依據硬指標最佳推薦（{geo_str}）"
            else:
                store_entry["ranking_reason"] = f"{base_status}（{'; '.join(detail_parts)}）"
                
            # 🛡️ 8. 封裝額外分析欄位
            store_entry["applied_strategy"] = sort_strategy
            store_entry["score_analysis"] = {
                "similarity": round(sim_val, 2),
                "rating": round(r_val / 5.0, 2),
                "popularity": round(p_val, 2),
                "distance": round(d_val, 2)
            }
            
            # 清理暫存用的向量欄位
            store_entry.pop("_geo_vector", None)  
            
            final_results.append(store_entry)
            seen_names.add(name)  

        return final_results