# app/services/hybrid_SQL_builder_service_v2.py
import json
import time
from app.utils.distance_utils import get_haversine_distance_sql # 匯入距離計算的SQL生成器
# from app.utils.distance_utils import _build_haversine_where_clause
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
    CANDIDATE_POOL_LIMIT = 500
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
        "cuisine": "pa.cuisine_type",
        "food_type": "pa.food_type",
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
        "cuisine": "pa.cuisine_type",
        "merchant_category": "pa.merchant_category",
        "restaurant_type": "pa.merchant_category"
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
            "sort_conditions": json_input.get("sort_conditions", []),
            "query_params": {},
            "page": json_input.get("page", 1),
            "page_size": json_input.get("page_size", 3),
            "vector_needed": False,
            "vector_keywords": {},
            "matrix_runtime_config": {"op": "AND", "feature_weights": {}}, # 🟢 補上初始宣告
            "photos_needed": False,
            "distance_needed": False,
            "user_location": None,
            "main_intent": json_input.get("main_intent", "query"),
            "need_time": False
        }
    
    # =================================================================
    # _scan_for_vector_intent 專用配置 (Vector Identification)
    # =================================================================
    # 哪些欄位被視為純語意搜尋欄位
    VECTOR_FIELDS = {"flavor", "review_summary", "cuisine"}
    
    # 哪些欄位屬於混合模式（同時存在於 SQL 與 Vector）
    HYBRID_FIELDS = {"food_type", "cuisine", "flavor", "facility_tags", "service_tags"}
    
    # 聯集：掃描器掃描目標
    ALL_VECTOR_TARGETS = VECTOR_FIELDS | HYBRID_FIELDS

    # =================================================================
    # _recursive_parse 專用配置 (SQL Logic Generation)
    # =================================================================

    
    # --- 欄位過濾與攔截 ---
    # 強制攔截：僅限向量處理，絕對禁止生成 SQL WHERE 子句
    VECTOR_ONLY_FIELDS = {
        "service_tags", "food_type", "cuisine"
    }

    
    # 特殊處理：強制轉換為 LIKE 模糊比對的欄位
    FORCE_LIKE_FIELDS = ["restaurant_type", "merchant_category", "restaurant_name", "address"]


    LIKE_TEMPLATE = "%{}%"


    @staticmethod
    def is_near_request(val_list, cmp):
        """
        統一判斷是否觸發地理位置過濾邏輯
        """
        has_location_keyword = any(str(item) == "使用者當前位置" for item in val_list)
        has_near_operator = cmp == "near"
        return has_location_keyword or has_near_operator

class HybridSQLBuilder:
    def __init__(self):
        # 實例化時不需要再重複定義映射表，直接引用 SQLSetting
        self.param_counter = 0
        self.query_params = {}
        self.user_location = None
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
        # 獲取使用者的經緯度
        # 獲取使用者的經緯度
        user_loc = json_input.get("user_location")

        # 安全防禦：確保 user_loc 是有效字典，且含有經緯度 Key，才進行格式化
        if isinstance(user_loc, dict) and any(k in user_loc for k in ["u_lat", "lat", "u_lng", "lng"]):
            lat_raw = user_loc.get("u_lat") or user_loc.get("lat")
            lng_raw = user_loc.get("u_lng") or user_loc.get("lng")
            
            lat_f = self.format_coordinate(lat_raw)
            lng_f = self.format_coordinate(lng_raw)
            has_valid_loc = (lat_f is not None and lng_f is not None)
        else:
            lat_f, lng_f = None, None
            has_valid_loc = False

        # 2. 檢查距離需求衝突
        requires_distance = (
            "distance" in json_input.get("info_needed", []) or 
            any(s.get("field") == "distance" for s in json_input.get("sort_conditions", []))
        )

        if requires_distance and not has_valid_loc:
            error_msg = "請求衝突：要求距離相關資訊但經緯度格式無效或精度不足。"
            logger.error(f"[SQL Builder][SID: {s_id}][終止查詢] {error_msg}")
            raise ValueError(error_msg)

        # 3. 座標判斷與注入
        if has_valid_loc:
            plan.update({
                "location_source": SQLSetting.LOC_SOURCE_USER,
                "distance_needed": True,
                "user_location": {
                    "lat": lat_f, # 已經是補齊至 6 位的小數 float
                    "lng": lng_f
                }
            })
            logger.info(f"[SQL Builder][SID: {s_id}] 使用高精度(自動補齊)使用者座標: {plan['user_location']}")
        else:
            plan.update({
                "location_source": SQLSetting.LOC_SOURCE_NONE,
                "distance_needed": False
            })
            logger.info(f"[SQL Builder][SID: {s_id}] 未偵測到有效座標，跳過位置相關處理")


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


        root_tree = json_input.get("logic_tree", {})
        plan["matrix_runtime_config"]["op"] = root_tree.get("op", "AND").upper()

        # 接下來維持原樣呼叫掃描器
        self._scan_for_vector_intent(root_tree, plan, s_id)
        plan["raw_logic_tree"] = json_input.get("logic_tree", {})
            
        logger.info(f"[SQL Builder][SID: {s_id}] 意圖解析完畢。全域算符: {plan['matrix_runtime_config']['op']}")
        log_function_timing("analyze_intent", s_id, time.perf_counter() - t0_analyze)

        return plan
    
    
    def _scan_for_vector_intent(self, node, plan, s_id):
        """
        深度優先掃描邏輯樹 (DFS)，提取向量搜尋意圖
        安全防禦版：100% 相容巢狀條件 (AND/OR) 與扁平單一條件結構
        """
        if not node or not isinstance(node, dict):
            return

        # 1. 處理容器型控制節點（包含子條件列表 conditions）
        if "conditions" in node and isinstance(node["conditions"], list):
            # 建立運行配置大腦字典，如果 plan 裡還沒有，就初始化它
            if "matrix_runtime_config" not in plan:
                plan["matrix_runtime_config"] = {
                    "op": node.get("op", "AND").upper(),  # 擷取該層運算子作為算符
                    "feature_weights": {}
                }
            
            # 遞迴向下鑽取
            for child in node["conditions"]:
                self._scan_for_vector_intent(child, plan, s_id)
            return

        # 2. 處理單一條件節點（相容扁平化結構與新/舊單一節點）
        # 💡 安全提權：使用安全分流確保不會對字串呼叫 .get()
        key_raw = node.get("field")
        key = key_raw.get("value") if isinstance(key_raw, dict) else key_raw
        
        val_raw = node.get("value")
        val = val_raw.get("value") if isinstance(val_raw, dict) else val_raw
        
        weight_raw = node.get("weight", 1.0)
        weight = weight_raw.get("value") if isinstance(weight_raw, dict) else weight_raw

        # 樣式 B 邊界保護（相容舊版自訂字典格式）
        if key is None:
            for k, v in node.items():
                if isinstance(v, dict) and "value" in v:
                    key = k
                    val = v.get("value")
                    weight = v.get("weight", 1.0)
                    break

        if not key or val is None:
            return

        # 資料歸一化 (確保轉換為字串陣列)
        processed_vals = val if isinstance(val, list) else [val]

        # 3. 如果命中向量特徵目標（去中心化打平收集，相容 V2 動態精排矩陣）
        if key in SQLSetting.ALL_VECTOR_TARGETS:
            if "vector_keywords" not in plan:
                plan["vector_keywords"] = {}
                
            if key not in plan["vector_keywords"]:
                plan["vector_keywords"][key] = []
            
            for item in processed_vals:
                item_str = str(item).strip()
                if not item_str:
                    continue
                if item_str not in plan["vector_keywords"][key]:
                    plan["vector_keywords"][key].append(item_str)
                
                # 關鍵聯動：將「欄位_特徵值」與「權重」精準對齊，塞進 V2 精排引擎配置中
                feat_id = f"{key}_{item_str}"
                if "matrix_runtime_config" not in plan:
                    plan["matrix_runtime_config"] = {"op": "AND", "feature_weights": {}}
                if "feature_weights" not in plan["matrix_runtime_config"]:
                    plan["matrix_runtime_config"]["feature_weights"] = {}
                
                plan["matrix_runtime_config"]["feature_weights"][feat_id] = float(weight)
                
            plan["vector_needed"] = True
            logger.info(f"[SQL Builder][SID: {s_id}] 成功捕捉動態語意特徵權重: {key} -> {processed_vals} (w: {weight})")
    

    # 負責將邏輯樹轉成sql字串
    # 會接收關鍵參數 vector_result_ids:這是向量資料庫搜尋完後回傳的Place id列表
    # 就是已經跑完向量搜尋了現在要生成到MySQL查詢店家的基本訊息
    # 移除參數 vector_result_ids：
    # 此參數從未在函式體內被使用，原設計意圖是將向量搜尋結果的 ID 傳入以限制 SQL 範圍，
    # 但實際上 ID 過濾邏輯已移至 VectorService，此處不再需要
    def build_sql(self, plan, user_location=None):
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

        # 使用 effective_loc 取代原本的 user_location
        effective_loc = plan.get("user_location") or user_location

        # 將 effective_loc 傳入遞迴解析器
        where_sql = self._recursive_parse(logic_tree, plan, s_id, user_location=effective_loc)

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
            

    def _recursive_parse(self, node, plan, s_id, user_location=None):
        """
        將巢狀 JSON 邏輯樹（包含單節點與多層容器）轉平為 SQL WHERE 字串
        支援：address 欄位的 IN/NOT IN 展開、near 降維警告、以及單節點邊界保護
        """
        if not node or not isinstance(node, dict): 
            return None
        
        # 處理邏輯運算子容器節點 (AND/OR 嵌套)
        if "op" in node and "conditions" in node:
            operator = node["op"].upper()
            child_sqls = []
            for child in node["conditions"]:
                child_sql = self._recursive_parse(child, plan, s_id, user_location=user_location)
                if child_sql:
                    child_sqls.append(child_sql)
            
            if not child_sqls: return None
            if len(child_sqls) == 1: return child_sqls[0]
            return f"({(f' {operator} ').join(child_sqls)})"

        # =================================================================
        # 2. 提取單一條件節點資訊 (相容樣式 A 與樣式 B 舊格式)
        # =================================================================
        key = node.get("field")
        val = node.get("value")
        cmp = str(node.get("cmp", "=")).strip().lower() # 🟢 歸一化轉小寫，方便比對 'near'、'between'、'open_at'

        if key is None:
            for k, v in node.items():
                if isinstance(v, dict) and "value" in v:
                    key = k
                    val = v.get("value")
                    cmp = str(v.get("cmp", "=")).strip().lower()
                    break

        if not key or val is None:
            return None

        # =================================================================
        # 3. 攔截純向量欄位 (如 service_tags, food_type 等已註冊於 VECTOR_ONLY_FIELDS 的欄位)
        # =================================================================
        if key in SQLSetting.VECTOR_ONLY_FIELDS:
            logger.info(f"[SQL Builder][SID: {s_id}] 強制攔截純向量欄位 '{key}'，不生成 SQL WHERE")
            return None

        # 數據歸一化 (單元素列表轉單一數值)
        if isinstance(val, list) and len(val) == 1:
            val = val[0]

        logger.info(f"[SQL Builder][SID: {s_id}] ===> [Recursive Parse] 處理欄位: '{key}' | 原始算符: {cmp} | 原始值: {val}")

        
        # 核心欄位映射處理
        if key in SQLSetting.SQL_WHERE_MAPPING:
            db_col = SQLSetting.SQL_WHERE_MAPPING[key]
            
            # 🟢 插入點：攔截 open_at 條件
            if cmp == "open_at":
                logger.info(f"[SQL Builder][SID: {s_id}] 偵測到營業時間過濾條件，標記 need_time")
                plan["need_time"] = True  # 🟢 標記為 True
                # 同時，如果有需要傳遞時間值，可以這樣存：
                plan["target_time"] = val 
                return None # 攔截 SQL 生成

            if key == "address":
                val_list = val if isinstance(val, list) else [val]
                
                # 1. 地理位置邏輯 (Near Request)
                if SQLSetting.is_near_request(val_list, cmp):
                    user_loc = user_location 
                    if user_loc and "lat" in user_loc and "lng" in user_loc:
                        limit_meter = node.get("distance", 500)
                        haversine_where = self._build_haversine_where_clause(
                            u_lat=user_loc["lat"], 
                            u_lng=user_loc["lng"], 
                            limit_meter=limit_meter
                        )
                        logger.info(f"[SQL Builder][SID: {s_id}] 已執行 'near' 邏輯：注入地理半徑 {limit_meter}m")
                        return haversine_where
                    else:
                        logger.error(f"[SQL Builder Error][SID: {s_id}] 偵測到 near 需求但未提供有效的 user_location")
                        return "1=0" 

                # 2. 一般地址模糊查詢邏輯 (當不是地理位置查詢時)
                if cmp in ["in", "not in"] or len(val_list) > 1:
                    if not val_list: return "1=0" if cmp != "not in" else "1=1"
                    like_clauses = []
                    for item in val_list:
                        p_name = f"p{self.param_counter}"
                        self.query_params[p_name] = SQLSetting.LIKE_TEMPLATE.format(item)
                        self.param_counter += 1
                        like_clauses.append(f"{db_col} LIKE %({p_name})s")
                    join_op = " AND " if cmp == "not in" else " OR "
                    if cmp == "not in":
                        like_clauses = [c.replace("LIKE", "NOT LIKE") for c in like_clauses]
                    return f"({join_op.join(like_clauses)})"
                else:
                    target_val = val_list[0]
                    p_name = f"p{self.param_counter}"
                    self.query_params[p_name] = SQLSetting.LIKE_TEMPLATE.format(target_val)
                    self.param_counter += 1
                    return f"{db_col} LIKE %({p_name})s"
                
            # -------------------------------------------------------------
            # 💡 【非 address 的一般欄位處理】 (維持原樣)
            # -------------------------------------------------------------
            p_name = f"p{self.param_counter}"
            cmp_upper = cmp.upper()

            # 強制模糊比對欄位 (如 restaurant_name)
            if key in SQLSetting.FORCE_LIKE_FIELDS or cmp_upper == "LIKE":
                target_val = val[0] if isinstance(val, list) else val
                param_value = target_val if "%" in str(target_val) else SQLSetting.LIKE_TEMPLATE.format(target_val)
                self.query_params[p_name] = param_value
                self.param_counter += 1
                return f"{db_col} LIKE %({p_name})s"

            # 標準 IN / NOT IN 集合查詢
            elif cmp_upper in ["IN", "NOT IN"]:
                val_list = val if isinstance(val, list) else [val]
                if not val_list: 
                    return "1=0" if cmp_upper == "IN" else "1=1"
                p_names = []
                for item in val_list:
                    current_p = f"p{self.param_counter}"
                    self.query_params[current_p] = item
                    p_names.append(f"%({current_p})s")
                    self.param_counter += 1
                return f"{db_col} {cmp_upper} ({', '.join(p_names)})"

            # 其餘標準精準比對 (例如時間、分數等)
            else:
                self.query_params[p_name] = val
                self.param_counter += 1
                return f"{db_col} {cmp_upper} %({p_name})s"
        
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

        t0_count_sql = time.perf_counter()

        where_sql = plan.get("_cached_where") 
        self.query_params = plan.get("_cached_params", {})        

        sql = "SELECT COUNT(DISTINCT p.id) AS total FROM all_places p "

        # --- 修改這裡：不論是 WHERE 還是 SELECT 欄位有用到 pa. 表，都必須 LEFT JOIN ---
        if (where_sql and "pa." in where_sql) or any("pa." in field for field in plan.get("select_fields", [])):
            sql += " LEFT JOIN Place_Attributes as pa ON p.id = pa.place_id "
        
        final_where = []
        if where_sql:
            final_where.append(where_sql)
            
        if plan.get("vector_needed") and vector_result_ids is not None:
            if len(vector_result_ids) > 0:
                ids_str = ",".join(str(int(x)) for x in vector_result_ids)
                final_where.append(f"p.id IN ({ids_str})")
            else:
                final_where.append("1=0")

        if final_where:
            sql += " WHERE " + " AND ".join(final_where)

        log_function_timing("build_count_sql", s_id, time.perf_counter() - t0_count_sql)

        return sql, self.query_params
    
    def _build_haversine_where_clause(self, u_lat, u_lng, limit_meter):
        """距離半徑算專用函式"""
        limit_km = limit_meter / 1000.0  
        p_lat = f"u_lat_{self.param_counter}"
        p_lng = f"u_lng_{self.param_counter}"
        p_dist = f"u_dist_{self.param_counter}"
        
        self.query_params[p_lat] = u_lat
        self.query_params[p_lng] = u_lng
        self.query_params[p_dist] = limit_km
        self.param_counter += 1
        
        return (
            f"(6371 * acos("
            f"cos(radians(%({p_lat})s)) * cos(radians(p.lat)) * "
            f"cos(radians(p.lng) - radians(%({p_lng})s)) + "
            f"sin(radians(%({p_lat})s)) * sin(radians(p.lat))"
            f")) <= %({p_dist})s"
        )
    

    def format_coordinate(self, val):
        """將座標強制補齊至小數點後 6 位並轉為 float"""
        if val is None:
            return None
        try:
            # 強制轉換並格式化為 6 位小數的字串
            formatted_val = "{:.6f}".format(float(val))
            return float(formatted_val)
        except (ValueError, TypeError) as e:
            logger.warning(f"[SQL Builder] 座標數字轉換失敗，傳入值: {val}，錯誤原因: {e}")
            return None