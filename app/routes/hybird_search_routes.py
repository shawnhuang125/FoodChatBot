
# app/routes/hybrid_search_routes.py
from fastapi import APIRouter, HTTPException, Body, Query,Request
from app.utils.performance_tracker import log_performance_to_csv
from app.utils.data_formatter import format_response_data   # 格式化搜尋結果與補上照片
from app.config import Config
from app.utils.app_logger import logger
from app.utils.quality_checker import check_search_status
from app.utils.quality_checker import evaluate_search_quality
from app.utils.quality_checker import analyze_search_results
import time


place_search = APIRouter()



@place_search.post("/place_search")
async def generate_query_and_search(
    request: Request,
    ai_to_api_data: dict = Body(...)
    ):
        """
        RAG混和查詢端點
        資料流說明: SQL BUILDER --> MYSQL --> VECTOR SERVICE --> QDRANT --> VECTOR SERVICE
        輸出內容會是第一頁

        GENERATE MODEL呼叫範例：
        POST https://192.168.1.118:5004/place_search

        {
        "s_id": "abc123",
        "status": "success",
        "data": {
            "is_fallback": false,
            "ai_behavior_hint": "...",
            "search_status": "success",
            "vector_search_info": { ... },
            "pagination": {
            "current_page": 1,
            "total_pages": 5,
            "total_results": 15,
            "page_size": 3
            },
            "final_results": [ ... ]
            }
        }
        """
        # 記錄整個請求的起始時間戳記（高精度計時器）
        # 為什麼用 perf_counter：perf_counter 提供比 time.time() 更高精度的相對時間，
        # 專為效能量測設計，不受系統時鐘調整影響（time.time() 可能因 NTP 校正而跳動）
        t0 = time.perf_counter()  # 整個請求開始

        # ── 【v1.0 舊版：per-request 實例化（已廢棄）】 ────────────────────
        # 原本的做法是在每次請求進來時，於此處直接 new 出所有 Service 實例。
        # 問題：VectorService() 內部會載入 BGE-M3 嵌入模型，每次初始化約需 1.7 秒，
        #       導致每個使用者的第一次搜尋請求都要額外等待，嚴重拖累 P50/P99 延遲。
        #       同時，高並發下會有多份模型同時存在記憶體，造成 OOM（記憶體溢出）風險。
        #
        # vector_service = VectorService()
        # builder       = HybridSQLBuilder()
        # rdbms_repo    = RdbmsRepository(use_mock=False)
        # session_cache = SearchSessionCache()

        # ── 【v2.0 新版：從 app.state 取出預載好的單例】 ──────────────────
        # 改動動機：將重型物件的初始化移至 startup_event（見 app/__init__.py）。
        # 好處：
        #   1. 冷啟動代價只付一次（服務啟動時），後續所有請求 0 延遲取用
        #   2. 所有請求共用同一份實例（Singleton），節省記憶體，避免競態
        #   3. 若 startup 失敗，服務不會啟動，而非等到請求進來才發現問題
        builder       = request.app.state.builder
        vector_service = request.app.state.vector_service
        rdbms_repo    = request.app.state.rdbms_repo
        session_cache = request.app.state.session_cache  # key 名稱需與 __init__.py 中 app.state.session_cache 一致

        # 獲取並檢查資料
        if not ai_to_api_data:
            # FastAPI 使用 raise HTTPException 來處理錯誤，這會自動轉換為 JSON 回傳給前端
            raise HTTPException(status_code=400, detail={"status": "fail", "message": "No data"})
        
        logger.info(f"fetched data: {ai_to_api_data}")

        try:

            all_ranked_results = []
            first_page_results = []
            quality_label = "no_data" # 預設狀態

            # 針對輸入的json進行分析意圖
            plan = builder.analyze_intent(ai_to_api_data)

            s_id = plan.get("s_id")

            # --- 階段一：SQL 查詢 ---
            rdb_info = {"status": "sql_no_data", "total_count": 0, "is_fallback": False}

            t_sql_start = time.perf_counter()

            final_sql, query_params = builder.build_sql(plan)
            logger.info(f"[Search][SID: {s_id}] 執行 SQL 查詢")

            db_results, _ = await rdbms_repo.execute_dynamic_query(final_sql, query_params, s_id)

            count_sql, count_params = builder.build_count_sql(plan)
            count_results, _ = await rdbms_repo.execute_dynamic_query(count_sql, count_params, s_id)

            t_sql_done = time.perf_counter()

            sql_service_duration = t_sql_done - t_sql_start


            total_count = count_results[0]['total'] if count_results else 0

            if total_count == 0:
                logger.warning(f"[Search][SID: {s_id}] SQL 查無資料，直接回傳")
                search_status = check_search_status([], plan, total_count=0)
                quality_label, is_fallback, ai_hint = evaluate_search_quality(
                    [],
                    {"status": "no_data", "message": ""},
                    rdb_info=rdb_info,
                    plan=plan
                )
                return {
                    "s_id": s_id,
                    "status": quality_label,
                    "data": {
                        "is_fallback": is_fallback,
                        "ai_behavior_hint": ai_hint,
                        "search_status": search_status,
                        "vector_search_info": {},
                        "pagination": {"current_page": 1, "total_pages": 0, "total_results": 0, "page_size": Config.PAGE_SIZE},
                        "final_results": []
                    }
                }

            rdb_info["total_count"] = total_count
            rdb_info["status"] = "exact_one_match" if total_count == 1 else "success"
            logger.info(f"[Search][SID: {s_id}] SQL 命中 {total_count} 筆")


            # --- 執行搜尋與權重排序 ---
            # 這裡直接取代掉原本從 vector_ids_for_sql 到 db_results = db_results[:3] 的所有內容
            t_sql_done = time.perf_counter()
            sql_service_duration = t_sql_done - t0

            all_ranked_results, vector_search_info = await vector_service.search_and_rank(
                db_results=db_results,
                plan=plan,
                total_count=total_count
            )
            t_vector_done = time.perf_counter()

            # 從 vector_search_info 取得 service 內部的細分秒數
            qdrant_duration = vector_search_info.get("qdrant_time", 0)
            ranking_duration = vector_search_info.get("ranking_time", 0)

            # 過渡耗時 = (Vector 總耗時) - (Qdrant 淨耗時) - (指標排序淨耗時)
            transition_duration = (t_vector_done - t_sql_done) - qdrant_duration - ranking_duration

            # --- 1. 格式化結果 ---
            all_ranked_results = format_response_data(all_ranked_results, plan)

            # --- 2. 執行分析門面 (搬移到這裡！) ---
            # 必須先執行這一步，才會產生 quality_label, is_fallback, ai_hint
            search_status, quality_label, is_fallback, ai_hint = analyze_search_results(
                all_ranked_results, 
                plan, 
                total_count, 
                vector_search_info, 
                rdb_info
            )


            session_data = {
                "results": all_ranked_results,
                "meta_analysis": {
                    "status": quality_label,
                    "is_fallback": is_fallback,
                    "ai_behavior_hint": ai_hint,
                    "search_status": search_status,
                    "vector_search_info": vector_search_info
                }
            }

            # --- 存入 Redis 分頁快取 ---
            # ── 【v3.0 進階版：獨立生成 6 碼隨機交易 SSID】 ──────────────────
            # 改動動機：
            #   1. 隱私防護：s_id 通常包含用戶識別或長字串，直接暴露在前端 URL 翻頁參數中有風險。
            #   2. 資源優化：6 碼短 ID 顯著減少 Redis Key 的儲存空間，對於百萬級併發快取更節省記憶體。
            #   3. URL 友善：翻頁 API (GET) 的參數更精簡 (例如: ?search_ssid=A7B2X9)，降低傳輸字元數。
            #   4. 狀態隔離：讓「對話 ID (s_id)」與「搜尋結果快取 (ssid)」生命週期分開處理，增加快取管理彈性。
        
            # --- 存入 Redis 並取得第一頁 (統一門面) ---
            # 此方法內建了：生成 6 碼隨機 SSID -> 序列化並儲存至 Redis -> 切出第 1 頁結果
            search_ssid, first_page_results, pagination_meta = await session_cache.create_session_and_get_first_page(
                all_ranked_results,
                page_size=Config.PAGE_SIZE
            )


            t_end = time.perf_counter()
            total_duration_route = t_end - t0

            performance_metrics = {
                "intent_content": vector_search_info.get("query_content"),  # 從 info 拿字串
                "hit_count": total_count,                                    # SQL 命中筆數
                "sql_service": round(sql_service_duration, 4),
                "transition": round(transition_duration, 4),
                "qdrant": round(qdrant_duration, 4),
                "ranking": round(ranking_duration, 4),
                "total": round(total_duration_route, 4)
            }

            log_performance_to_csv(performance_metrics)

            # 回傳精簡後的 Response 物件
            response = {
                "s_id": plan.get("s_id"),  # 原本的 s_id 照常回傳給 AI 識別
                "search_ssid": search_ssid, # 新的 6 碼短 ID 給前端翻頁用
                "status": quality_label,   # 狀態: success / partial_success / no_data
                "data": {
                        # 保底旗標
                        # 意義：是否觸發了「退而求其次」的邏輯
                        # 描述：True 代表結果並非 100% 符合 AI 解析出的語意關鍵字，是給 AI 判斷語氣的最快開關
                        # 用途1：對 AI (LLM)：作為**「信心判斷」**的快速開關。AI 看到 True 就應自動切換為「謙虛模式」，避免對搜尋結果過度承諾
                        # 用途2：對前端 UI：用於決定是否顯示**「相似推薦」或「精選替代」**的警示 UI 標籤，讓用戶知道搜尋結果並非精確匹配
                        "is_fallback": is_fallback,

                        # AI 行為指南
                        # 意義：後端對生成式模型的「口頭交代」
                        # 描述：根據搜尋品質生成的文字指令。AI 應將此內容納入 Context，決定要「邀功」還是「致歉」
                        # 用途1: 對 AI (LLM)：直接作為 System Message 的補充內容。模型會根據此文字決定對話策略
                        # 用途2: 對除錯 (Debug)：讓開發者在不用進入向量庫查看分數的情況下，直接透過 API 回傳結果一眼看出「為什麼 AI 會用這種語氣說話」
                        "ai_behavior_hint": ai_hint,

                        # 搜尋狀態診斷
                        # 意義：描述底層 SQL 與向量庫的匹配狀況
                        # 描述：例如 "skipped" (跳過向量), "no_match" (搜尋無果), "success" (搜尋成功)
                        # 用途：主要給後端除錯或前端顯示診斷訊息使用
                        "search_status": search_status,

                        # 向量搜尋元數據
                        # 意義：記錄向量資料庫（Qdrant/Milvus）的執行細節
                        # 內容：包含搜尋到的原始分數 (Score)、匹配的店家 ID 清單等
                        # 用途：用於驗證 AI 推薦的相似度權重是否合理
                        "vector_search_info": vector_search_info,

                        # 分頁元數據
                        # 意義：告知前端目前是第幾頁、總共幾頁，讓前端決定是否顯示「下一頁」按鈕
                        # 內容：current_page / total_pages / total_results / page_size / session_ttl_seconds
                        "pagination": pagination_meta,

                        # 第一頁推薦清單
                        # 意義：經過 Hybrid Ranking 後的第 1 頁店家（固定 3 筆）
                        # 描述：後續翻頁請呼叫 GET /place_search/page?search_ssid=xxx&page=N
                        "final_results": first_page_results
                }
            }

            return response

        except Exception as e:
            logger.error(f"Search API Error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


@place_search.get("/place_search/page")
async def get_search_page(
    request: Request,
    search_ssid: str = Query(..., description="搜尋 Session 識別碼（來自 POST /place_search 回傳的 s_id）"),
    page: int = Query(..., ge=1, description="欲取得的頁碼（從 1 開始）")
):
    """
    翻頁端點：從 Redis 快取取得指定頁的搜尋結果。

    為什麼用 GET 而非 POST：
    取特定頁的資料是「讀取」語意，符合 RESTful 規範；
    同時 GET 請求可被瀏覽器與 CDN 快取，降低重複讀取壓力。

    GENERATE MODEL呼叫範例：
    GET https://192.168.1.118:5004/place_search/page?search_ssid=abc123&page=2

    :param search_ssid:  POST /place_search 回傳的 s_id 欄位
    :param page:         頁碼（最小為 1）
    :return:             指定頁的店家列表 + 分頁元數據
    """
    try:
        # 從 app.state 取得快取實例
        session_cache = request.app.state.session_cache
        
        # 先確認 Session 是否還活著
        if not await session_cache.exists(search_ssid):
            raise HTTPException(
                status_code=404,
                detail={"status": "session_expired", "message": "搜尋 Session 已過期"}
            )

        # 從 Redis 取出指定頁資料
        page_results, pagination_meta = await session_cache.get_page(
            search_ssid,
            page=page,
            page_size=Config.PAGE_SIZE
        )

        logger.info(
            f"[Page API] search_ssid={search_ssid}, page={page}, "
            f"回傳 {len(page_results)} 筆"
        )

        return {
            "s_id": search_ssid,
            "status": "success",
            "data": {
                # 分頁元數據（與 POST 回傳格式一致，方便前端統一處理）
                # 內容：current_page / total_pages / total_results / page_size / session_ttl_seconds
                # 為什麼格式要與 POST 一致：前端只需要寫一套分頁邏輯，不需要針對首頁與翻頁分別處理
                "pagination": pagination_meta,
                # 本頁店家推薦清單
                "final_results": page_results
            }
        }

    except HTTPException:
        # 直接重新拋出，避免被下方的通用 Exception 捕獲而失去 status_code
        # 為什麼需要這層：Python 的 except Exception 會捕獲所有繼承自 Exception 的類別，
        # 包含 HTTPException，若不先攔截會導致 404/422 等語意錯誤被包成 500 回傳
        raise

    except Exception as e:
        logger.error(f"[Page API] 翻頁失敗: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))