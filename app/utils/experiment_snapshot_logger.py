import os
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.utils.app_logger import logger

EXPERIMENT_SNAPSHOT_DIR = os.path.join("logs", "experiments", "snapshots")

def log_experiment_snapshot(
    plan: Dict[str, Any],
    flat_features: List[tuple],
    candidates_count: int,
    passed_gate_count: int,
    final_results: List[Dict[str, Any]],
    all_store_diagnostics: List[Dict[str, Any]],
    logic_threshold: float,
    sort_strategy: str,
    weights: Dict[str, float],
    fusion_operator: str = "log_geometric",
    custom_dir: Optional[str] = None
) -> str:
    """
    【實驗專用 - 完整評測快照輸出器】
    保存當次搜尋的所有詳細數據，包含：
    1. 元資料（Session ID、時間、門檻、權重設定、檢索特徵、聚合算子）
    2. 標註槽位（自動預填所有候選店家的評分字典）
    3. 召回漏斗（SQL候選數 -> 邏輯閘通過數 -> 最終輸出數）
    4. 最終重排名單（Rank, Hybrid Score, 推薦理由）
    5. 所有候選店家的各項細部維度分數（包含被門檻刷掉的店家）
    
    回傳：儲存的檔案絕對路徑
    """
    try:
        target_dir = custom_dir or EXPERIMENT_SNAPSHOT_DIR
        os.makedirs(target_dir, exist_ok=True)

        s_id = str(plan.get("s_id", "unknown_sid")).strip()
        safe_sid = re.sub(r'[^a-zA-Z0-9_-]', '_', s_id)
        safe_op = re.sub(r'[^a-zA-Z0-9_-]', '_', str(fusion_operator).strip())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 抽取向量關鍵字並以 + 串接，排除 pure_sort 預設保底
        raw_keywords = [
            str(feat[2]).strip()
            for feat in flat_features
            if len(feat) >= 3 and str(feat[2]).strip() and feat[0] != "pure_sort"
        ]
        
        if raw_keywords:
            cleaned_keywords = [re.sub(r'[\\/*?:"<>| \t\n\r]', '_', kw) for kw in raw_keywords]
            kw_part = "+".join(cleaned_keywords)
        else:
            kw_part = "pure_metric"

        # 2. 組合檔名
        filename = f"snapshot_{safe_sid}_op-{safe_op}_kw-{kw_part}_th{logic_threshold:.2f}_{timestamp}.json"
        filepath = os.path.join(target_dir, filename)

        # 整理查詢特徵清單
        features_queried = [
            {
                "field_key": feat[0],
                "query_sentence": feat[1],
                "clean_keyword": feat[2]
            }
            for feat in flat_features
        ]

        # 整理最終輸出名單精簡摘要
        final_summary = []
        for rank_idx, store in enumerate(final_results, start=1):
            final_summary.append({
                "rank": rank_idx,
                "restaurant_id": store.get("id"),
                "restaurant_name": store.get("restaurant_name"),
                "hybrid_score": store.get("hybrid_score"),
                "semantic_similarity": store.get("semantic_similarity"),
                "score_analysis": store.get("score_analysis", {}),
                "ranking_reason": store.get("ranking_reason", "")
            })

        # 3. 自動預留打分數的鍵值對
        ground_truth_template = {}
        for c in all_store_diagnostics:
            rid = str(c.get("restaurant_id"))
            rname = str(c.get("restaurant_name", "未知店家"))
            ground_truth_template[rid] = {
                "name": rname,
                "label": None  # 👈 待填分數: 2=完全符合, 1=部分符合, 0=不符合
            }

        # 4. 組裝全量結構
        snapshot_payload = {
            "metadata": {
                "session_id": s_id,
                "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fusion_operator": fusion_operator,
                "logic_threshold": logic_threshold,
                "sort_strategy": sort_strategy,
                "normalized_weights": weights,
                "executed_vector_queries": plan.get("executed_vector_queries", []),
                "features_queried": features_queried
            },
            "annotation": {
                "note": "請在 label 填入分數 (2=完全符合, 1=部分符合, 0=不符合)",
                "ground_truth_labels": ground_truth_template
            },
            "recall_funnel": {
                "total_candidates_from_sql": candidates_count,
                "passed_gate_count": passed_gate_count,
                "gate_pass_rate": round(passed_gate_count / candidates_count, 4) if candidates_count > 0 else 0.0,
                "final_output_count": len(final_results)
            },
            "final_ranked_summary": final_summary,
            "all_candidates_diagnostics": all_store_diagnostics
        }

        with open(filepath, mode="w", encoding="utf-8") as f:
            json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

        logger.info(f"📊 [Experiment Snapshot] 評測基準快照已存檔: {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"❌ [Experiment Snapshot] 輸出快照失敗 (SID: {plan.get('s_id')}): {e}", exc_info=True)
        return ""