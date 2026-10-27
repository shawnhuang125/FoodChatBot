from typing import List, Dict, Any, Optional, Tuple
from app.repository.vector_repository import VectorRepository
from sentence_transformers import SentenceTransformer
import numpy as np
import math
import asyncio
import time
import torch
import json
import os
from app.utils.app_logger import logger
from app.config import Config
from app.utils.performance_tracker import log_semantic_scores_to_csv
from app.utils.experiment_snapshot_logger import log_experiment_snapshot

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


    # 語意與邏輯閘門檻設定 (Thresholds)
    # 語意與邏輯閘門檻設定 (Thresholds)
    DEFAULT_LOGIC_THRESHOLD: float = 0.52        # 建議由 0.60 改為 0.52
    DYNAMIC_THRESHOLD_FLOOR: float = 0.52        # 建議由 0.60 改為 0.52
    DYNAMIC_THRESHOLD_SPAN: float = 0.05         # 0.52 + 0.05 * weight (最大 0.57)

    # 理由包裝與評價文案門檻
    SEMANTIC_HIGH_THRESHOLD: float = 0.60        # 降至 0.60
    SEMANTIC_MEDIUM_THRESHOLD: float = 0.52      # 降至 0.52


    # 人氣與距離指標等級門檻
    METRIC_HIGH_THRESHOLD: float = 0.85            # 「人氣爆棚 / 距離極近」門檻
    METRIC_MEDIUM_THRESHOLD: float = 0.50          # 「人氣頗高 / 距離適中」門檻


    # 相似度搜尋欄位映射表
    VECTOR_FIELD_MAPPING = {
        # 菜系與食物種類全面雙向廣播
        "cuisine": ["food_tags_vector"],
        "cuisine_type": ["food_tags_vector"],
        "food_type": ["food_tags_vector"],
        "flavor": ["flavor_vector"],
        "facility_tags": ["facility_tags_vector"],
        "service_tags": ["service_tags_vector", "facility_tags_vector", "review_summary_vector"],
        "review_summary": ["review_summary_vector"],
    }
    DEFAULT_FALLBACK_VECTOR = ["passage_all_vector"]  # 自訂/自由文本檢索使用的通道
    # 🎯 單一未具名向量集合（Single Vector Space）請設為 [None]
    # DEFAULT_FALLBACK_VECTOR = [None]

def min_max_rescale(val: np.ndarray, floor_val: float = 0.65, ceil_val: float = 1.2) -> np.ndarray:
    """將通過門檻的分數線性展開至 [0.0, 1.0]，保留各維度相對鑑別度"""
    span = max(ceil_val - floor_val, 1e-6)
    return np.clip((val - floor_val) / span, 0.0, 1.0)


def execute_fusion_operator(
    matrix: np.ndarray, 
    weights_vec: np.ndarray, 
    operator_type: str = "log_geometric"
) -> np.ndarray:
    """
    matrix: (N, 4) - 包含 [similarity, rating, popularity, distance]，均位於 [0.0, 1.0]
    weights_vec: (4,) - 權重向量，總和為 1.0
    operator_type: 實驗變因
      - 'log_geometric': 對數空間幾何乘積聚合 (單項過低會有嚴格懲罰)
      - 'linear_weighted': 線性加權總和 (基準線 Baseline)
      - 'log_sum_exp': 非線性平滑極值聚合 (凸顯最突出優勢維度)
    """
    eps = 1e-4
    op = operator_type.lower()

    if op == "log_geometric":
        log_matrix = np.log(matrix + eps)
        contribution_matrix = log_matrix * weights_vec
        total_log_scores = np.sum(contribution_matrix, axis=1)
        return np.exp(total_log_scores)

    elif op == "linear_weighted":
        return np.dot(matrix, weights_vec)

    elif op == "log_sum_exp":
        tau = 0.25  # 溫度係數
        scaled = matrix / tau + np.log(weights_vec + eps)
        max_val = np.max(scaled, axis=1, keepdims=True)
        lse = max_val.squeeze(axis=1) + tau * np.log(np.sum(np.exp(scaled - max_val), axis=1))
        # 歸一化回 [0, 1] 方便與其他算子基準比較
        return lse / np.max(lse) if np.max(lse) > 0 else lse

    else:
        # 預設 Fallback 到加權幾何
        log_matrix = np.log(matrix + eps)
        return np.exp(np.sum(log_matrix * weights_vec, axis=1))

class VectorService:
    def __init__(self):
        # 1. 從環境變數讀取掛載路徑
        self.model_path = os.path.abspath(Config.EMBEDDING_MODEL_PATH)

        # 2. 鋼鐵嚴格檢查：若未設定環境變數，或該路徑下的 config.json 不存在，直接拋出例外拒絕啟動
        if not self.model_path or not os.path.exists(
            os.path.join(self.model_path, "config.json")
        ):
            error_msg = (
                "模型掛載失敗，請確認是否 .env 檔案有寫入 EMBEDDING_MODEL_PATH"
            )
            logger.critical(
                f"❌ [Model Mount Error] {error_msg} (當前路徑: '{self.model_path}')"
            )
            # 強制拋出 RuntimeError 終止 startup，絕不連外網下載
            raise RuntimeError(error_msg)
        
        # 3. 自動判定硬體裝置 (Docker 容器內為 cpu)
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

        logger.info(
            f"偵測到本地掛載模型，正在從 {self.model_path} 載入 BGE-M3 至 [{device.upper()}]..."
        )
        self.model = SentenceTransformer(self.model_path, device=device)
        logger.info(f"BGE-M3 模型已成功載入並運行於 [{device.upper()}]")

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

        info: Dict[str, Any] = {"status": "processing", "message": ""}
        flat_features = []  
        task_weights: List[float] = []

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
                
                # 🟢 將 cuisine 與 food_type 合流，統一使用廣義餐飲料理模板
                if field_key in ["cuisine", "food_type", "cuisine_type"]:
                    # 針對飯麵類微調即可，其餘直接用 clean_item
                    if clean_item in ["飯", "飯類"]:
                        query_sentence = "飯"
                    elif clean_item in ["麵", "麵類"]:
                        query_sentence = "麵食"
                    else:
                        query_sentence = clean_item
                        
                elif field_key in ["service_tags", "facility_tags"]:
                    # 拿掉「的所有」，受詞統一對齊「餐飲店家」
                    query_sentence = f"有提供{clean_item}的餐飲店家"
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

        detailed_channel_scores = {str(rid): {} for rid in rdbms_ids}

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

            plan["executed_vector_queries"] = ["無(純指標保底)"]
            
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

            # 為了將實際執行的自然語言檢索字串保存到 plan 裡，供 CSV 輸出
            plan["executed_vector_queries"] = query_sentences

            query_vectors = self.model.encode(
                query_sentences, 
                normalize_embeddings=True, 
                convert_to_numpy=True
            ).tolist() # type: ignore

            q_start = time.perf_counter()


            # 2. 逐一通道進行分流運算與多路召回

            for i, (f_key, _, _) in enumerate(flat_features):
                target_vector_names = RankSettings.VECTOR_FIELD_MAPPING.get(
                    f_key, 
                    RankSettings.DEFAULT_FALLBACK_VECTOR
                )
                if isinstance(target_vector_names, str):
                    target_vector_names = [target_vector_names]

                # 初始化每家店在此特徵映射通道的分數（預設 0.0）
                feat_store_channels = {
                    str(rid): {vec_name: 0.0 for vec_name in target_vector_names}
                    for rid in rdbms_ids
                }

                # 針對映射到的所有向量通道發起查詢
                search_tasks = [
                    self.repo.search_in_ids(
                        query_vector=query_vectors[i],
                        rdbms_ids=rdbms_ids,
                        vector_name=vec_name
                    )
                    for vec_name in target_vector_names
                ]
                
                multi_channel_results = await asyncio.gather(*search_tasks)

                # 逐通道紀錄各店家的個別分數
                for vec_name, channel_results in zip(target_vector_names, multi_channel_results):
                    all_vector_results.extend(channel_results)
                    for v in channel_results:
                        rid_str = str(v.id)
                        if rid_str in feat_store_channels:
                            feat_store_channels[rid_str][vec_name] = float(v.score)

                # 將融合後的代表分 (取 Max) 填入主矩陣，並保存各通道詳細分數
                for rid in rdbms_ids:
                    rid_str = str(rid)
                    ch_scores = feat_store_channels[rid_str]
                    best_score = max(ch_scores.values()) if ch_scores else 0.0
                    
                    restaurant_features[rid_str].append(best_score)
                    detailed_channel_scores[rid_str][i] = ch_scores

            q_end = time.perf_counter()
            info["qdrant_time"] = q_end - q_start


        final_results = await self._apply_hybrid_ranking_v2(
            db_map=db_map,                 
            flat_features=flat_features,   
            matrix_data=restaurant_features, 
            plan=plan,           
            task_weights=task_weights,
            detailed_channel_scores=detailed_channel_scores,  
            vector_results=all_vector_results,
            logic_threshold=kwargs.get('logic_threshold', RankSettings.DEFAULT_LOGIC_THRESHOLD)  
        )
        
        r_end = time.perf_counter()
        info.update({
            "status": "completed",
            "updated_total_count": len(final_results),
            "ranking_time": round(r_end - r_start, 4),
            "message": f"搜尋成功：已篩選出 {len(final_results)} 筆結果。",
            "raw_score_matrix": plan.get("all_candidates_raw_scores", [])
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

        # 補上這兩行，直接終結 Pylance 報錯
        v_logic_tree = plan.get("matrix_runtime_config", {}).get("vector_logic_tree")
        
        # 如果全部的向量特徵只有 service_tags，則將其也視為主意圖，不能排除乾淨
        main_intent_indices = [idx for idx, (field, _, _) in enumerate(flat_features) if field != "service_tags"]
        if not main_intent_indices:
            main_intent_indices = list(range(len(flat_features)))

       # 1. 動態權重分配
        valid_conditions: List[str] = [
            str(cond.get("field")) for cond in sort_conditions 
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
        service_tags_map = {}
        for v in raw_vector_results:
            v_id_str = str(v.id)
            v_summary = getattr(v, "review_summary", "") or ""
            v_service_tags = getattr(v, "service_tags", None) or []
            
            # 只有當這家餐廳還沒存過摘要，或者新拿到的摘要長度大於原本存的長度，才允許寫入/更新
            if v_id_str not in summary_map or len(v_summary) > len(summary_map[v_id_str]):
                # 確保存進去的不是純空格或預設的無內容字串
                if v_summary.strip() and v_summary != "暫無精選評論摘要":
                    summary_map[v_id_str] = v_summary
                
                # 取得 service_tags（若取得非空 list 則記錄/覆蓋）
                if v_service_tags and (v_id_str not in service_tags_map or len(v_service_tags) > len(service_tags_map[v_id_str])):
                    service_tags_map[v_id_str] = v_service_tags
        
        all_counts = [row.get('user_ratings_total', 0) for row in db_map.values()]
        max_reviews_log = math.log1p(max(all_counts)) if all_counts and max(all_counts) > 0 else 1.0

        # 組裝真實相似度矩陣 (N x M)
        S_matrix = np.array([matrix_data[v_id] for v_id in v_ids_order])
        HARD_THRESHOLD = kwargs.get('logic_threshold', RankSettings.DEFAULT_LOGIC_THRESHOLD)


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
        # 1. 建立各維度特徵的動態門檻表
        # 權重在 0.0 ~ 0.5 區間映射至 0.60 ~ 0.65
        th_floor = getattr(RankSettings, "DYNAMIC_THRESHOLD_FLOOR", 0.60)
        th_span = getattr(RankSettings, "DYNAMIC_THRESHOLD_SPAN", 0.05)

        feature_dynamic_thresholds = []
        for idx, (f_k, _, item_k) in enumerate(flat_features):
            w = float(task_weights[idx]) if idx < len(task_weights) else 0.2
            clamped_w = min(max(w, 0.0), 1.0)
            dynamic_th = th_floor + (th_span * clamped_w)
            feature_dynamic_thresholds.append(round(dynamic_th, 4))

        logger.info(
            f"[精排大腦][SID: {s_id}] 特徵動態門檻配置: " + 
            ", ".join([f"{feat[0]}_{feat[2]}(w={task_weights[i]:.2f}) -> 門檻:{feature_dynamic_thresholds[i]}" 
                       for i, feat in enumerate(flat_features)])
        )

        # 2. 邏輯閘內套用對應維度的動態門檻
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

                f_key = str(node.get("field") or "")
                val_list = node.get("value", [])
                if not isinstance(val_list, list): 
                    val_list = [val_list]
                
                leaf_mask = np.zeros(S_matrix.shape[0])
                for item in val_list:
                    clean_item = str(item).strip()
                    idx_dim = feat_to_idx.get((f_key, clean_item))
                    
                    if idx_dim is None and f_key in ["cuisine", "food_type", "cuisine_type"]:
                        for alt_key in ["cuisine", "food_type", "cuisine_type"]:
                            if (alt_key, clean_item) in feat_to_idx:
                                idx_dim = feat_to_idx[(alt_key, clean_item)]
                                break
                    
                    if idx_dim is not None:
                        scores_dim = S_matrix[:, idx_dim]
                        
                        # 🟢 套用該維度專屬的動態門檻
                        cur_threshold = feature_dynamic_thresholds[idx_dim]
                        item_mask = (scores_dim >= cur_threshold) & (scores_dim > 0.0)
                        leaf_mask = np.maximum(leaf_mask, item_mask.astype(float))
                                                
                return leaf_mask

            gate_mask_vector = evaluate_vector_tree(v_logic_tree)
        else:
            gate_mask_vector = np.ones(len(v_ids_order))

        failed_count = len(v_ids_order) - int(np.sum(gate_mask_vector))
        passed_gate_count = int(np.sum(gate_mask_vector))
        logger.info(f"[精排大腦][SID: {s_id}] 階段一精準向量邏輯閘過濾完成。總候選: {len(v_ids_order)} | 通過: {int(np.sum(gate_mask_vector))} | 被生死門硬攔截: {failed_count}")


        detailed_channel_scores = kwargs.get("detailed_channel_scores", {})

        # =================================================================
        # 🟢 論文實驗資料自動記錄：包含各通道個別分數
        # =================================================================
        raw_scores_data = []
        for idx_mat, v_id in enumerate(v_ids_order):
            store_db = db_map.get(v_id, {})
            passed = bool(gate_mask_vector[idx_mat])
            store_ch_detail = detailed_channel_scores.get(v_id, {})
            
            feat_list = []
            for feat_idx, (f_key, _, clean_item) in enumerate(flat_features):
                raw_content = store_db.get(f_key, "")
                if raw_content is None:
                    raw_content = ""

                # 取出此特徵在所有映射向量通道的獨立分數
                channel_breakdown = store_ch_detail.get(feat_idx, {})

                feat_list.append({
                    "field_key": f_key,                          
                    "target_keyword": clean_item,                
                    "store_raw_array": str(raw_content),         
                    "score": float(S_matrix[idx_mat, feat_idx]), # 融合代表分 (Max)
                    "channel_scores": channel_breakdown          # 🟢 每個通道獨立分數
                })

        # ==========================================
        # 🟢 階段二：對剩下的店家用 service_tags 進行加權排序
        # ==========================================
        
        service_indices = [
            idx for idx, (field, _, _) in enumerate(flat_features) if field == "service_tags"
        ]

        qualified_stores = []
        all_candidate_diagnostics = []

        for idx_mat, v_id in enumerate(v_ids_order):

            store = db_map[v_id]
            scores = S_matrix[idx_mat]
            
            # 1. 核心主意圖分數計算 (套用動態門檻)
            # 1. 核心主意圖分數計算 (套用動態門檻)
            if main_intent_indices:
                active_pairs = [
                    (float(scores[idx]), float(task_weights[idx]))
                    for idx in main_intent_indices
                    if idx < len(scores) and scores[idx] >= feature_dynamic_thresholds[idx]
                ]
                if active_pairs:
                    sub_scores, sub_weights = zip(*active_pairs)
                    w_sum = sum(sub_weights)
                    if w_sum > 0:
                        core_base_score = float(np.average(sub_scores, weights=sub_weights))
                    else:
                        core_base_score = float(np.mean(sub_scores))
                else:
                    core_base_score = th_floor  # 🟢 修正：對齊前面定義的 th_floor
            else:
                core_base_score = th_floor      # 🟢 修正：對齊前面定義的 th_floor

            # 2 & 3. 服務標籤依權重給予紅利 (越在意的服務命中加越多，未命中扣分)
            match_count = 0
            weighted_bonus = 0.0
            weighted_penalty = 0.0

            for idx_dim in service_indices:
                if idx_dim < len(scores):
                    _, _, item = flat_features[idx_dim]
                    v_score = float(scores[idx_dim])
                    w = float(task_weights[idx_dim]) if idx_dim < len(task_weights) else 0.2
                    db_val = str(store.get("service_tags", "") or "")
                    
                    # 🟢 改用該服務特徵專屬的動態門檻
                    dim_th = feature_dynamic_thresholds[idx_dim]
                    is_string_match = item in db_val if db_val else False
                    is_matched = is_string_match or (v_score >= dim_th)

                    if is_matched:
                        match_count += 1
                        # 權重越高的標籤，帶來的加乘紅利越顯著 (例如權重 0.4 -> +20%)
                        weighted_bonus += (w * 0.50)
                    else:
                        # 使用者指定的服務未滿足，依其重視程度扣分 (例如權重 0.4 -> -6%)
                        weighted_penalty += (w * 0.15)

            soft_preference_modifier = 1.0 + weighted_bonus - weighted_penalty
            soft_preference_modifier = max(0.5, soft_preference_modifier)  # 防禦性下限保底

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


            passed_gate = bool(gate_mask_vector[idx_mat] == 1.0)
            # 🟢 記錄所有店家（不管有沒有過門檻都記錄）
            all_candidate_diagnostics.append({
                "restaurant_id": v_id,
                "restaurant_name": store.get("restaurant_name"),
                "passed_gate": passed_gate,
                "raw_feature_scores": {
                    f"{feat[0]}_{feat[2]}": round(float(scores[f_idx]), 4)
                    for f_idx, feat in enumerate(flat_features)
                },
                "core_base_score": round(core_base_score, 4),
                "service_match_count": match_count,
                "soft_preference_modifier": round(soft_preference_modifier, 4),
                "raw_similarity_score": round(similarity_score, 4),
                "rating_score": round(rating_score, 4),
                "popularity_score": round(popularity_score, 4),
                "distance_score": round(distance_score, 4),
                "hybrid_score": None,
                "final_rank": None
            })

            # 🟢 記完之後，沒過門檻的店家在這裡才攔截！
            if not passed_gate:
                continue

            store_entry = store.copy()
            store_entry["_geo_vector"] = [similarity_score, rating_score, popularity_score, distance_score]
            qualified_stores.append(store_entry)

        fusion_operator = plan.get("matrix_runtime_config", {}).get("fusion_operator", "log_geometric")


        # ==========================================
        # 🟢 多目標聚合降維重排 (無 Sigmoid，支援多算子實驗)
        # ==========================================
        if not qualified_stores:
            logger.warning(f"[精排大腦][SID: {s_id}] 無任何店家通過門檻，記錄快照並返回空列表")
            log_experiment_snapshot(
                plan=plan,
                flat_features=flat_features,
                candidates_count=len(v_ids_order),
                passed_gate_count=passed_gate_count,
                final_results=[],
                all_store_diagnostics=all_candidate_diagnostics,
                logic_threshold=HARD_THRESHOLD,
                sort_strategy=sort_strategy,
                weights=weights,
                fusion_operator=fusion_operator
            )
            return []

        # ==========================================
        # 🟢 多目標聚合降維重排
        # ==========================================
        matrix = np.array([s["_geo_vector"] for s in qualified_stores], dtype=float)
        weights_vec = np.array([
            weights["similarity"], 
            weights["rating"], 
            weights["popularity"], 
            weights["distance"]
        ], dtype=float)

        fusion_operator = plan.get("matrix_runtime_config", {}).get("fusion_operator", "log_geometric")

        # 只有在 matrix 大小大於 0 時才進行切片
        if matrix.shape[0] > 0:
            matrix[:, 0] = min_max_rescale(matrix[:, 0], floor_val=HARD_THRESHOLD, ceil_val=1.2)
            raw_scores = execute_fusion_operator(matrix, weights_vec, operator_type=fusion_operator)
            # 確保始終是一維陣列，防止單筆結果降維為 scalar 導致 index 報錯
            final_scores = np.atleast_1d(raw_scores)
        else:
            final_scores = np.array([])

        # 🔴 把原本下面重複的這行徹底刪除！
        # final_scores = execute_fusion_operator(matrix, weights_vec, operator_type=fusion_operator)

        for idx, store_entry in enumerate(qualified_stores):
            store_entry["hybrid_score"] = round(float(final_scores[idx]), 4)
            # 記錄標準化後的語意維度分數
            store_entry["semantic_similarity"] = round(float(matrix[idx][0]), 4)

        qualified_stores.sort(key=lambda x: x["hybrid_score"], reverse=True)

        if qualified_stores:
            top_3 = [(str(s.get("restaurant_name") or ""), s.get("hybrid_score")) for s in qualified_stores[:3]]
            logger.info(
                f"[精排大腦][SID: {s_id}] 多目標重排結束 (使用算子: '{fusion_operator}')。"
                f"進入理由包裝店家數: {len(qualified_stores)} | 前三名預覽: {top_3}"
            )

        final_results = self._package_final_results(
            qualified_stores=qualified_stores,
            matrix_data=matrix_data,
            flat_features=flat_features,
            must_constraints=must_constraints,
            summary_map=summary_map,
            service_tags_map=service_tags_map,
            weights=weights,
            plan=plan,
            sort_strategy=sort_strategy,
            hard_threshold=HARD_THRESHOLD,
            fusion_operator=fusion_operator,
            task_weights=task_weights,
            detailed_channel_scores=detailed_channel_scores,   
            feature_dynamic_thresholds=feature_dynamic_thresholds  # 動態門檻清單
        )

        # 回填排名到診斷表
        diag_map = {str(d["restaurant_id"]): d for d in all_candidate_diagnostics}
        for rank_idx, store in enumerate(final_results, start=1):
            s_vid = str(store.get("id"))
            if s_vid in diag_map:
                diag_map[s_vid]["hybrid_score"] = store.get("hybrid_score")
                diag_map[s_vid]["final_rank"] = rank_idx

        # 🟢 存檔 (加上安全保護，避免快照記錄錯誤中斷主程式)
        try:
            log_experiment_snapshot(
                plan=plan,
                flat_features=flat_features,
                candidates_count=len(v_ids_order),
                passed_gate_count=int(np.sum(gate_mask_vector)),
                final_results=final_results,
                all_store_diagnostics=all_candidate_diagnostics,
                logic_threshold=HARD_THRESHOLD,
                sort_strategy=sort_strategy,
                weights=weights,
                fusion_operator=fusion_operator
            )
            logger.info(f"[精排大腦][SID: {s_id}] 實驗快照存檔成功！")
        except Exception as snap_err:
            logger.error(f"[精排大腦][SID: {s_id}] 快照存檔失敗: {snap_err}", exc_info=True)

        return final_results

    
    
    def _package_final_results(
        self,
        qualified_stores: List[Dict[str, Any]],
        matrix_data: Dict[str, List[float]],
        flat_features: List[Tuple[str, str, str]],
        must_constraints: Dict[str, List[str]],
        summary_map: Dict[str, str],
        service_tags_map: Dict[str, Any],
        weights: Dict[str, float],
        plan: Dict[str, Any],
        sort_strategy: str,
        hard_threshold: float,
        fusion_operator: str = "log_geometric",
        task_weights: Optional[List[float]] = None,
        detailed_channel_scores: Optional[Dict[str, Any]] = None,
        feature_dynamic_thresholds: Optional[List[float]] = None
    ) -> List[Dict[str, Any]]:
        seen_names = set()
        final_results = []
        t_weights = task_weights or [0.2] * len(flat_features)

        # 🟢 修正 1：明確從 RankSettings 讀取語意門檻
        high_th = getattr(RankSettings, "SEMANTIC_HIGH_THRESHOLD", 0.65)
        med_th = getattr(RankSettings, "SEMANTIC_MEDIUM_THRESHOLD", 0.60)

        # 🟢 修正 2：指標門檻與 fallback 基準對齊
        metric_high = getattr(RankSettings, "METRIC_HIGH_THRESHOLD", 0.85)
        metric_med = getattr(RankSettings, "METRIC_MEDIUM_THRESHOLD", 0.50)

        for store_entry in qualified_stores:
            name = store_entry.get("restaurant_name")
            if name in seen_names:
                continue

            v_id = str(store_entry.get("id"))
            scores = matrix_data.get(v_id, [0.0])
            store_entry = store_entry.copy()

            store_entry["review_summary"] = summary_map.get(
                v_id, store_entry.get("review_summary", "暫無精選評論摘要")
            )

            # service_tags 與 facility_tags 解析
            qdrant_service_tags = service_tags_map.get(v_id)
            if qdrant_service_tags:
                store_entry["service_tags"] = qdrant_service_tags
            else:
                raw_st = store_entry.get("service_tags")
                if isinstance(raw_st, str) and raw_st.strip():
                    try:
                        store_entry["service_tags"] = json.loads(raw_st)
                    except Exception:
                        store_entry["service_tags"] = [s.strip() for s in raw_st.split(",") if s.strip()]
                elif not raw_st:
                    store_entry["service_tags"] = []

            raw_tags = store_entry.get("facility_tags")
            if raw_tags and isinstance(raw_tags, str):
                try:
                    store_entry["facility_tags"] = json.loads(raw_tags)
                except Exception:
                    store_entry["facility_tags"] = []
            else:
                store_entry["facility_tags"] = store_entry.get("facility_tags", [])

            # 🛡️ 4. 逐一特徵解析相關性
            dimension_diagnostics = []
            strong_keywords = []
            weak_keywords = []
            unmatched_keywords = []

            store_ch_map = (detailed_channel_scores or {}).get(v_id, {})

            if flat_features and flat_features[0][0] != "pure_sort":
                for idx_dim, (field_key, _, item) in enumerate(flat_features):
                    if idx_dim < len(scores):
                        channel_score = float(scores[idx_dim])
                        feat_w = float(t_weights[idx_dim]) if idx_dim < len(t_weights) else 0.2
                        
                        # 🟢 取得各通道獨立分數字典，如 {"service_tags_vector": 0.85, "facility_tags_vector": 0.42}
                        per_channel_scores = {
                            k: round(v, 4) for k, v in store_ch_map.get(idx_dim, {}).items()
                        }

                        # 🟢 若屬於餐飲類別，將 cuisine 與 food_type 合併檢查
                        if field_key in ["cuisine", "food_type", "cuisine_type"]:
                            c_val = str(store_entry.get("cuisine", "") or "")
                            f_val = str(store_entry.get("food_type", "") or "")
                            db_val = f"{c_val} {f_val}".strip()
                        else:
                            db_val = str(store_entry.get(field_key, "") or "")

                        fac_val = str(store_entry.get("facility_tags", "") or "")
                        ser_val = str(store_entry.get("service_tags", "") or "")

                        clean_item = item.replace("有", "").replace("提供", "").strip()
                        is_exact_db = (
                            (item in db_val) or (item in fac_val) or (item in ser_val) or
                            (clean_item in fac_val) or (clean_item in ser_val)
                        )

                        # 🟢 取得該特徵專屬的動態門檻 (fallback 為 med_th)
                        cur_dyn_th = (
                            feature_dynamic_thresholds[idx_dim] 
                            if feature_dynamic_thresholds and idx_dim < len(feature_dynamic_thresholds) 
                            else med_th
                        )

                        if is_exact_db or channel_score >= high_th:
                            correlation = "強相關"
                            strong_keywords.append((feat_w, item))
                            reason_note = "資料庫標籤精準命中" if is_exact_db else f"語意相似度達 {channel_score:.2f} (達高度符合門檻 {high_th})"
                        elif channel_score >= cur_dyn_th:
                            correlation = "弱相關"
                            weak_keywords.append((feat_w, item))
                            reason_note = f"語意相似度達 {channel_score:.2f} (達動態權重門檻 {cur_dyn_th:.3f})"
                        else:
                            correlation = "未符合"
                            unmatched_keywords.append((feat_w, item))
                            reason_note = f"相似度僅 {channel_score:.2f} (未達動態權重門檻 {cur_dyn_th:.3f})"

                        # 將通道分數組裝成可讀字串供 explanation 顯示
                        ch_detail_str = " | ".join([f"{k}: {v:.4f}" for k, v in per_channel_scores.items()])

                        dimension_diagnostics.append({
                            "field": field_key,
                            "keyword": item,
                            "weight": round(feat_w, 3),
                            "score": round(channel_score, 4),           # 最佳代表分
                            "channel_scores": per_channel_scores,        # 🟢 回傳該特徵下每個通道的個別分數
                            "exact_match": is_exact_db,
                            "correlation": correlation,
                            "explanation": f"欄位[{field_key}]關鍵字「{item}」(權重:{feat_w:.2f}) 判定為【{correlation}】：{reason_note}"
                                           + (f" [各通道得分: {ch_detail_str}]" if ch_detail_str else "")
                        })

            # 🛡️ 5. 讀取標準化指標
            geo_vector = store_entry.get("_geo_vector", [0.0, 0.0, 0.0, 1.0])
            sim_val = geo_vector[0]
            r_val = geo_vector[1] * 5.0
            p_val = geo_vector[2]
            d_val = geo_vector[3]

            # 🛡️ 6. 產生自然的指標語句
            rating_desc = f"{r_val:.1f} 星好評" if r_val >= 4.0 else f"評分 {r_val:.1f} 星"
            pop_desc = None
            if weights.get("popularity", 0) > 0:
                if p_val >= metric_high:
                    pop_desc = "超人氣排隊名店"
                elif p_val >= metric_med:
                    pop_desc = "在地人氣頗高"
                else:
                    pop_desc = "客群穩定"

            dist_desc = None
            if weights.get("distance", 0) > 0 and plan.get("distance_needed"):
                if d_val >= metric_high:
                    dist_desc = "距離極近"
                elif d_val >= metric_med:
                    dist_desc = "距離適中"
                else:
                    dist_desc = "距離稍遠"

            # 🛡️ 7. 🟢 自然語言（語意化）理由組裝
            strong_keywords.sort(key=lambda x: x[0], reverse=True)
            weak_keywords.sort(key=lambda x: x[0], reverse=True)

            sentence_clauses = []

            # (1) 強相關描繪
            if strong_keywords:
                matched_items = "、".join([kw for _, kw in strong_keywords[:3]])
                sentence_clauses.append(f"精準符合您對「{matched_items}」的需求")

            # (2) 弱相關描繪
            if weak_keywords:
                weak_items = "、".join([kw for _, kw in weak_keywords[:2]])
                if strong_keywords:
                    sentence_clauses.append(f"並兼具「{weak_items}」等相關特色")
                else:
                    sentence_clauses.append(f"具備「{weak_items}」等相關特色風味")

            # (3) 🟢 口碑與評價描述（修正銜接詞）
            quality_parts = [f"獲 {rating_desc}"]
            if pop_desc:
                quality_parts.append(pop_desc)
            sentence_clauses.append("且" + "、".join(quality_parts))

            # (4) 地理位置描述
            if dist_desc:
                sentence_clauses.append(f"{dist_desc}")

            # 組裝最終推薦理由
            if flat_features and flat_features[0][0] == "pure_sort":
                natural_reason = f"依據周邊指標精選：獲 {rating_desc}，{pop_desc or '客群穩定'}" + (f"，{dist_desc}" if dist_desc else "") + "。"
            elif not strong_keywords and not weak_keywords:
                natural_reason = f"綜合考量推薦：獲 {rating_desc}，{pop_desc or '客群穩定'}" + (f"，{dist_desc}" if dist_desc else "") + "。"
            else:
                natural_reason = "，".join(sentence_clauses) + "。"

            store_entry["ranking_reason"] = natural_reason

            # 🛡️ 8. 封裝輸出
            store_entry["dimension_diagnostics"] = dimension_diagnostics
            store_entry["applied_strategy"] = sort_strategy
            store_entry["applied_operator"] = fusion_operator
            store_entry["score_analysis"] = {
                "similarity_norm": round(sim_val, 2),
                "rating": round(r_val / 5.0, 2),
                "popularity": round(p_val, 2),
                "distance": round(d_val, 2)
            }

            store_entry.pop("_geo_vector", None)
            final_results.append(store_entry)
            seen_names.add(name)

        return final_results