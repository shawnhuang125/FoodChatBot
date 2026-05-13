# app/services/hybrid_SQL_builder_service_v2.py
import json
import time
from app.utils.distance_utils import get_haversine_distance_sql # 匯入距離計算的SQL生成器
from app.utils.performance_tracker import log_function_timing    # 函式層級耗時記錄器
from app.utils.app_logger import logger
import copy

class SQLSetting:
    """
    統一管理所有 SQL 構建所需的配置項
    """
    # =================================================================
    # 全域策略配置 (Global Strategy)
    # =================================================================
    # 支援的搜尋模式
    SUPPORTED_INTENTS = ["recommend", "query"]
    
    # CANDIDATE_POOL_LIMIT: SQL 撈取店家的總上限
    # SQL 階段的初步排序邏輯
    CANDIDATE_POOL_LIMIT = 300
    CANDIDATE_POOL_ORDER_BY = "p.rating DESC, p.user_ratings_total DESC"


    # =================================================================
    # 地理位置與距離配置 (Geospatial)
    # =================================================================
    
    # 座標來源枚舉
    LOC_SOURCE_USER = "user"
    LOC_SOURCE_DEFAULT = "default"
    LOC_SOURCE_NONE = "none"

    # 系統統一使用的經緯度與距離 Key (用於 plan 與 SQL Alias)
    LAT_KEY = "lat"
    LNG_KEY = "lng"
    DISTANCE_FIELD_KEY = "distance"
    
    # =================================================================
    # 欄位映射配置 (Field Mappings)
    # =================================================================
    # 用於 SELECT 子句：Key 為 API 輸出名, Value 為 DB 實體欄位
    FIELD_MAPPING = {
        "id": "p.id", 
        "restaurant_name": "p.name", 
        "address": "p.address", 
        "rating": "p.rating",
        "phone": "p.phone",       
        "website": "p.website",
        "opening_hours": "p.opening_hours",
        "user_ratings_total": "p.user_ratings_total",
        "cuisine_type": "pa.cuisine_type",
        "merchant_category": "pa.merchant_category",
        "facility_tags": "pa.facility_tags",
        #"lat": "p.lat",
        #"lng": "p.lng",
    }

    # 用於 WHERE 子句：對應原始資料表欄位
    SQL_WHERE_MAPPING = {
        "id": "p.id",
        "restaurant_name": "p.name",         
        "phone": "p.phone",       
        "website": "p.website",   
        "opening_hours": "p.opening_hours",
        "user_ratings_total": "p.user_ratings_total",
        "time": "p.opening_hours",
        "address": "p.address", 
        "rating": "p.rating",
        "cuisine_type": "pa.cuisine_type",
        "merchant_category": "pa.merchant_category",
        "restaurant_type": "pa.merchant_category",
        "內用": "pa.has_dine_in",
        "冷氣": "pa.has_air_conditioner",
        "外帶": "pa.has_takeout",
        "吃到飽": "pa.is_all_you_can_eat",
        "特約停車場": "pa.has_private_parking"
    }

    # =================================================================
    # analyze_intent 專用配置 (Intent Analysis)
    # =================================================================
    # query 模式下的保底必選欄位
    QUERY_BASE_FIELDS = {
        "id": "p.id",
        "restaurant_name": "p.name",
        "address": "p.address",
        "rating": "p.rating",
        "reviews_count": "p.user_ratings_total",
        "facility_tags": "pa.facility_tags",
        #"lat": "p.lat",
        #"lng": "p.lng"
    }

    @staticmethod
    def get_initial_plan(s_id, json_input):
        """ 初始化搜尋計畫的標準結構 """
        return {
            "s_id": s_id,
            "location_source": "none",
            "select_fields": [],
            "sort_clauses": [],
            "sort_conditions": json_input.get("sort_conditions", []),
            "query_params": {},
            "page": json_input.get("page", 1),
            "page_size": json_input.get("page_size", 3),
            "vector_needed": False,
            "vector_keywords": {},
            "photos_needed": False,
            "distance_needed": False,
            "user_location": None,
            "main_intent": json_input.get("main_intent", "query")
        }
    
    # =================================================================
    # _scan_for_vector_intent 專用配置 (Vector Identification)
    # =================================================================
    # 哪些欄位被視為純語意搜尋欄位
    VECTOR_FIELDS = {"flavor", "review_summary", "cuisine_type"}
    
    # 哪些欄位屬於混合模式（同時存在於 SQL 與 Vector）
    HYBRID_FIELDS = {"food_type", "cuisine_type", "flavor", "facility_tags", "service_tags"}
    
    # 聯集：掃描器掃描目標
    ALL_VECTOR_TARGETS = VECTOR_FIELDS | HYBRID_FIELDS

    # =================================================================
    # _recursive_parse 專用配置 (SQL Logic Generation)
    # =================================================================

    
    # --- 欄位過濾與攔截 ---
    # 強制攔截：僅限向量處理，絕對禁止生成 SQL WHERE 子句
    VECTOR_ONLY_FIELDS = {
        "service_tags", "food_type", "cuisine_type",
        "內用", "冷氣", "外帶", "吃到飽", "特約停車場", 
        "行動支付", "現金支付", "信用卡"
    }

    
    # 特殊處理：強制轉換為 LIKE 模糊比對的欄位
    FORCE_LIKE_FIELDS = ["restaurant_type", "merchant_category", "restaurant_name", "address"]

    # 標籤映射：用於 TINYINT (1/0) 的精確匹配判斷
    FACILITY_KEYS = {
        "內用", "冷氣", "外帶", "吃到飽", "特約停車場", 
        "行動支付", "現金支付", "信用卡" 
    }

    LIKE_TEMPLATE = "%{}%"

class HybridSQLBuilder:
    def __init__(self):
        # 實例化時不需要再重複定義映射表，直接引用 SQLSetting
        self.param_counter = 0
        self.query_params = {}
    # 只負責看懂 JSON，告訴你需不需要跑向量搜尋
    # 解析意圖
    # 回傳一個字典,包含SQL所需的結構以及向量搜尋的需求
    def analyze_intent(self, json_input):
        s_id = json_input.get("s_id")
        # 記錄函式起始時間，用於計算整體意圖解析耗時
        # 為什麼放在 s_id 取得之後：s_id 是 logging 必要參數，取得後才有辦法完整記錄這筆計時
        t0_analyze = time.perf_counter()
        
        if not s_id:
            raise ValueError("Missing s_id: 多用戶環境下必須提供 Session ID")
        
        logger.info(f"[SQL Builder][SID: {s_id}] 開始解析使用者意圖")
        # 查詢用的json資料方便做處理
        plan = SQLSetting.get_initial_plan(s_id, json_input)

        # 獲取使用者的經緯度
        # 如果有[info_needed] = 包含distance需求或sort_condition有距離排序
        # 但沒有usder_location就先用預設的經緯度
        user_loc = json_input.get("user_location")
        wants_distance = (
            "distance" in json_input.get("info_needed", []) or 
            any(s.get("field") == "distance" for s in json_input.get("sort_conditions", []))
        )

        # 3. 座標判斷邏輯
        # 狀況 A: 使用者提供了正確座標
        if user_loc and "lat" in user_loc and "lng" in user_loc:
            plan.update({
                "location_source": SQLSetting.LOC_SOURCE_USER,
                "distance_needed": True,
                "user_location": user_loc
            })
            logger.info(f"[SQL Builder][SID: {s_id}] 使用使用者提供座標: {user_loc}")
            
        # 狀況 B: 沒接收到使用者經緯度
        else:
            plan.update({
                "location_source": SQLSetting.LOC_SOURCE_NONE,
                "distance_needed": False
            })
            # 僅記錄日誌，不做任何座標注入處理
            logger.info(f"[SQL Builder][SID: {s_id}] 未偵測到使用者座標，跳過位置相關處理")



        # 解析意圖模式
        # 如果意圖的值為"recommend""
        # main_intent如果等於("recommand")無視info_needed,直接選擇所有欄位並推薦模式強制開啟照片提供功能
        # query一般查詢模式
        # 取得意圖並轉小寫處理
        intent = json_input.get("main_intent", "query").strip().lower()

        # 檢查是否在支援的模式白名單中
        if intent not in SQLSetting.SUPPORTED_INTENTS:
            error_msg = f"Unsupported main_intent: '{intent}'. 系統僅支援 {SQLSetting.SUPPORTED_INTENTS}"
            logger.error(f"[SQL Builder][SID: {s_id}] {error_msg}")
            raise ValueError(error_msg)

        plan["main_intent"] = intent


        if intent == "recommend":
            logger.info(f"[SQL Builder][SID: {s_id}] 進入推薦模式: 全選欄位並強制開啟照片")
            # 直接從 SQLSetting 注入所有定義好的欄位
            for key, db_col in SQLSetting.FIELD_MAPPING.items():
                plan["select_fields"].append(f"{db_col} AS {key}")
            # 推薦模式強制需求
            plan["photos_needed"] = True
        
        elif intent == "query":
            logger.info(f"[SQL Builder][SID: {s_id}] 進入一般查詢模式: 按需注入欄位")
            # 1. 先注入保底基礎欄位
            for key, db_col in SQLSetting.QUERY_BASE_FIELDS.items():
                plan["select_fields"].append(f"{db_col} AS {key}")
            

            # 加入使用者在 info_needed 指定的額外欄位
            for info in json_input.get("info_needed",[]):
                # 處理照片需求
                if info == "photos":
                    plan["photos_needed"] = True

                # 處理距離需求
                elif info == "distance" and user_loc:
                    # 距離欄位由 build_sql 階段動態生成 SQL，此處僅標記需求
                    continue
                
                # 處理一般欄位
                elif info in SQLSetting.FIELD_MAPPING:
                    # 避免重複加入 base_fields 已有的欄位
                    col_sql = f"{SQLSetting.FIELD_MAPPING[info]} AS {info}"
                    if col_sql not in plan["select_fields"]:
                        plan["select_fields"].append(col_sql)

        else:
            # --- 邊界保護：未知意圖處理 ---
            error_msg = f"Unsupported main_intent: '{intent}'. 系統僅支援 'recommend' 或 'query'。"
            logger.error(f"[SQL Builder][SID: {s_id}] {error_msg}")
            
            # 拋出異常，讓 Route 層的 try-except 捕捉並回傳 400 Bad Request 給 API 用戶
            raise ValueError(error_msg)



        # 處理Sort排序規則,包括distance排序問題
        for s in json_input.get("sort_conditions", []):
            field = s['field']
            method = s['method']
            if field == "distance":
                if plan["distance_needed"]:
                    plan["sort_clauses"].append(f"distance {method}") # 不要加p.
                    logger.debug(f"[SQL Builder] 加入距離排序: {method}")
            else:
                # 一般欄位
                plan["sort_clauses"].append(f"p.{field} {method}")
            # 直接組裝排序的子句,通常傳入的json裡面的sort_conditions會是像這樣:
            # ["sort_conditions": [
            #{
                #"field": "distance",
                #"method": "ASC"
                #},
            #]
            # 所以使用append直接組合起來變成""p.rating DESC"
            # 加入倒PLAN的sort_clauses的list裡面就會是order by 子句
            # 如果是 'distance' 排序，通常需要在外部算好距離後再處理，Distance模組還沒有處理!
            # 若要'distance' 排序會sql執行錯誤,原因是資料庫沒有這個欄位
        # 預先掃描邏輯樹，分離 SQL 條件與向量條件
        # 把原始 logic_tree 存下來，在 build_sql 時才遞迴生成
        # 這裡先掃描是否有向量需求
        self._scan_for_vector_intent(json_input.get("logic_tree", {}), plan, s_id)
        # 把原始邏輯樹存入 plan，留給第二階段用
        plan["raw_logic_tree"] = json_input.get("logic_tree", {})

        # 如果有向量需求,那排序就要放到向量斯尋完畢之後處理

        if plan["vector_needed"]:
            plan["deferred_sorting"] = True
            plan["order_by_distance"] = any(s.get("field") == "distance" for s in json_input.get("sort_conditions", []))
            logger.info(f"[SQL Builder][SID: {s_id}] 檢測到向量需求，排序將延遲至 VectorService")
        else:
            plan["deferred_sorting"] = False
            plan["order_by_distance"] = False

        # 記錄 analyze_intent 函式總耗時至 CSV
        log_function_timing("analyze_intent", s_id, time.perf_counter() - t0_analyze)

        return plan
    

    def _scan_for_vector_intent(self, node, plan, s_id):
        if not node or not isinstance(node, dict):
            return

        # 1. 處理容器型節點 (帶有 conditions 的 AND/OR)
        if "conditions" in node and isinstance(node["conditions"], list):
            for child in node["conditions"]:
                self._scan_for_vector_intent(child, plan, s_id)
            return # 處理完子節點就結束

        # 2. 處理葉子節點 (條件節點)
        key = None
        val = None

        # 樣式 A: {"field": "address", "value": "..."}
        if "field" in node:
            key = node.get("field")
            val = node.get("value")
        # 樣式 B: {"address": {"value": "..."}}
        else:
            keys = list(node.keys())
            if keys:
                potential_key = keys[0]
                # 確保內容是字典才能用 .get
                if isinstance(node[potential_key], dict):
                    key = potential_key
                    val = node[potential_key].get("value")

        # 如果沒抓到 Key 或 Value，代表不是有效的條件，跳過
        if key is None or val is None:
            return

        # 3. 數值轉換與向量標記邏輯 (保持不變)
        if isinstance(val, list):
            processed_val = " ".join([str(i) for i in val])
        else:
            processed_val = str(val)

        if key in SQLSetting.ALL_VECTOR_TARGETS:
            if key not in plan["vector_keywords"]:
                plan["vector_keywords"][key] = []
            
            # 確保是 list 才能 append
            if not isinstance(plan["vector_keywords"][key], list):
                plan["vector_keywords"][key] = [str(plan["vector_keywords"][key])]
                
            plan["vector_keywords"][key].append(processed_val)
            plan["vector_needed"] = True
            logger.info(f"[SQL Builder][SID: {s_id}] 捕捉語意特徵: {key} -> {processed_val}")
            

    # 負責將邏輯樹轉成sql字串
    # 會接收關鍵參數 vector_result_ids:這是向量資料庫搜尋完後回傳的Place id列表
    # 就是已經跑完向量搜尋了現在要生成到MySQL查詢店家的基本訊息
    # 移除參數 vector_result_ids：
    # 此參數從未在函式體內被使用，原設計意圖是將向量搜尋結果的 ID 傳入以限制 SQL 範圍，
    # 但實際上 ID 過濾邏輯已移至 VectorService，此處不再需要
    def build_sql(self, plan, is_fallback=False):
        """
        建構全量候選池 SQL：已移除 SQL 分頁邏輯並實施 100% 變數解耦
        """
        s_id = plan.get("s_id")
        t0_build_sql = time.perf_counter()
        logger.info(f"[SQL Builder][SID: {s_id}] 開始建構候選池查詢 SQL (Candidate Pool Mode)")

        # 1. 取得plan中的邏輯樹暫存
        logic_tree = plan.get("raw_logic_tree", {})

        # 2. 重置參數計數器
        self.param_counter = 0 
        self.query_params = {} 

        # 3. 遞迴生成 WHERE 子句
        where_sql = self._recursive_parse(logic_tree, s_id)

        if logic_tree and not where_sql:
            logger.warning(f"[SQL Builder][SID: {s_id}] 警告：偵測到邏輯樹但解析結果為空，可能存在格式不符或欄位未定義")
        
        # 暫存快取資訊
        plan.update({
            "_cached_where": where_sql,
            "_cached_params": copy.deepcopy(self.query_params),
            "generated_where_clause": where_sql,
            "query_params": self.query_params
        })

        # 4. 處理地理位置與距離 SQL (解耦座標 Key)
        if plan.get("distance_needed") and plan.get("user_location"):
            u_loc = plan["user_location"]
            # 引用 SQLSetting 的座標 Key 與距離欄位名
            dist_sql = get_haversine_distance_sql(
                u_loc[SQLSetting.LAT_KEY], 
                u_loc[SQLSetting.LNG_KEY]
            )
            dist_alias = f"{dist_sql} AS {SQLSetting.DISTANCE_FIELD_KEY}"
            
            # 避免重複注入
            if not any(f"AS {SQLSetting.DISTANCE_FIELD_KEY}" in f for f in plan["select_fields"]):
                plan["select_fields"].append(dist_alias)

        # 5. 組裝 SQL 片段
        sql_parts = [
            f"SELECT {', '.join(plan['select_fields'])}",
            "FROM all_places p",
            "LEFT JOIN Place_Attributes as pa ON p.id = pa.place_id"
        ]
        
        if where_sql:
            sql_parts.append(f"WHERE {where_sql}")
        
        sql_parts.append("GROUP BY p.id")

        # 6. 候選池排序與限量 (完全解耦配置)
        # 統一採用大池子策略，確保 Redis 分頁有足夠候選店家
        sql_parts.append(f"ORDER BY {SQLSetting.CANDIDATE_POOL_ORDER_BY}")
        sql_parts.append(f"LIMIT {SQLSetting.CANDIDATE_POOL_LIMIT}")

        final_sql = " ".join(sql_parts)

        logger.info(f"[SQL Builder] 候選池模式：LIMIT {SQLSetting.CANDIDATE_POOL_LIMIT}，已跳過 SQL OFFSET 分頁")
        
        # 記錄耗時
        log_function_timing("build_sql", s_id, time.perf_counter() - t0_build_sql)

        return final_sql, self.query_params
            

    def _recursive_parse(self, node, s_id):
        """
        將巢狀 JSON 邏輯樹轉平為 SQL WHERE 字串
        完全移除 Full-text Search，強制使用精準比對與標準 LIKE
        """
        if not node or not isinstance(node, dict): 
            return None
        
        # 1. 處理邏輯運算子節點 (AND/OR)
        if "op" in node and "conditions" in node:
            operator = node["op"].upper()
            child_sqls = []
            for child in node["conditions"]:
                child_sql = self._recursive_parse(child, s_id)
                if child_sql:
                    child_sqls.append(child_sql)
            
            if not child_sqls: return None
            if len(child_sqls) == 1: return child_sqls[0]
            return f"({(f' {operator} ').join(child_sqls)})"

        # 2. 提取欄位資訊 (相容樣式 A 與樣式 B)
        key = node.get("field")
        val = node.get("value")
        cmp = node.get("cmp", "=").upper()

        if key is None:
            for k, v in node.items():
                if isinstance(v, dict) and "value" in v:
                    key = k
                    val = v.get("value")
                    cmp = v.get("cmp", "=").upper()
                    break

        if not key or val is None:
            return None

        # 3. 攔截向量欄位
        if key in SQLSetting.VECTOR_ONLY_FIELDS or key in SQLSetting.VECTOR_FIELDS:
            logger.info(f"[SQL Builder][SID: {s_id}] 攔截向量欄位 '{key}'")
            return None

        # 數據歸一化 (單元素列表轉數值)
        if isinstance(val, list) and len(val) == 1:
            val = val[0]

        logger.info(f"[SQL Builder][SID: {s_id}] ===> [Recursive Parse] 處理欄位: '{key}' | 算符: {cmp} | 原始值: {val}")

        # 4. 生成 SQL 
        # 狀況 A: 設施標籤 (TINYINT 1/0)
        if key in SQLSetting.FACILITY_KEYS:
            if val is not True: return None
            db_col = SQLSetting.SQL_WHERE_MAPPING.get(key)
            if not db_col: return None
            p_name = f"p{self.param_counter}"
            self.query_params[p_name] = 1
            self.param_counter += 1
            return f"{db_col} = %({p_name})s"
        
        # 狀況 B: 一般映射欄位
        if key in SQLSetting.SQL_WHERE_MAPPING:
            db_col = SQLSetting.SQL_WHERE_MAPPING[key]
            p_name = f"p{self.param_counter}"

            # --- 1. 【優先攔截】強制模糊比對欄位 ---
            # 只要在 FORCE_LIKE_FIELDS 裡，管你 cmp 傳什麼，通通轉 LIKE
            if key in SQLSetting.FORCE_LIKE_FIELDS or cmp == "LIKE":
                # LIKE 只能處理單一值，如果是 list 則取第一個
                target_val = val[0] if isinstance(val, list) else val
                
                # 補上模板 (例如 %{}%)
                param_value = target_val if "%" in str(target_val) else SQLSetting.LIKE_TEMPLATE.format(target_val)
                self.query_params[p_name] = param_value
                self.param_counter += 1
                return f"{db_col} LIKE %({p_name})s"

            # --- 2. 處理集合查詢 (IN / NOT IN) ---
            elif cmp in ["IN", "NOT IN"]:
                val_list = val if isinstance(val, list) else [val]
                if not val_list: 
                    return "1=0" if cmp == "IN" else "1=1"
                p_names = []
                for item in val_list:
                    current_p = f"p{self.param_counter}"
                    self.query_params[current_p] = item
                    p_names.append(f"%({current_p})s")
                    self.param_counter += 1
                return f"{db_col} {cmp} ({', '.join(p_names)})"

            # --- 3. 標準精準比對 ---
            else:
                self.query_params[p_name] = val
                self.param_counter += 1
                return f"{db_col} {cmp} %({p_name})s"
        
        logger.warning(f"!!! [SQL Builder Warning] 欄位 '{key}' 找不到 Mapping 配置")
        return None

    # 移除參數 is_fallback：
    # 此參數從未在函式體內被使用，導致 Fallback 輪的 Count SQL 與主查詢條件不一致（Count 仍用嚴格條件）
    # 若未來需要修正此邏輯不一致，應在此處呼叫 _strip_strict_conditions 套用放寬條件後再計算總數
    def build_count_sql(self, plan, vector_result_ids=None):
        """
        生成用於計算店家總筆數的 SQL
        """
        s_id = plan.get("s_id")
        logger.info(f"[SQL Builder][SID: {s_id}] 開始建構總數統計 SQL (Count Query)")
        # 確保 Count 查詢從 p0 開始，且不殘留舊參數 ---

        # 記錄 count SQL 建構起始時間，用於觀察 Count 查詢的 SQL 組裝是否有效率瓶頸
        # 為什麼單獨計時：Count SQL 與主查詢 SQL 的條件邏輯相同，但通常更快；若兩者耗時差異過大，代表 recursive_parse 有異常
        t0_count_sql = time.perf_counter()

        where_sql = plan.get("_cached_where") 
        self.query_params = plan.get("_cached_params", {})        


        sql = "SELECT COUNT(DISTINCT p.id) AS total FROM all_places p "
        # 實驗性測試：拿掉 JOIN
        # sql += " LEFT JOIN Place_Attributes as pa ON p.id = pa.place_id"

        # 如果 WHERE 子句中有提到 pa. (來自屬性表)，就必須 JOIN，否則 SQL 會報錯
        if where_sql and "pa." in where_sql:
            sql += " LEFT JOIN Place_Attributes as pa ON p.id = pa.place_id "
        
        final_where = []

        if where_sql:
            final_where.append(where_sql)
            
        # 向量 ID 邏輯保持不變
        if plan.get("vector_needed") and vector_result_ids is not None:
            if len(vector_result_ids) > 0:
                ids_str = ",".join(str(int(x)) for x in vector_result_ids)
                final_where.append(f"p.id IN ({ids_str})")
            else:
                final_where.append("1=0")

        if final_where:
            sql += " WHERE " + " AND ".join(final_where)

        # 記錄 build_count_sql 函式總耗時至 CSV
        log_function_timing("build_count_sql", s_id, time.perf_counter() - t0_count_sql)

        return sql, self.query_params
    
    