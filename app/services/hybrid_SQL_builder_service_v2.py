# app/services/hybrid_SQL_builder_service_v2.py
import json
import time
from app.utils.distance_utils import get_haversine_distance_sql # 匯入距離計算的SQL生成器
from app.utils.performance_tracker import log_function_timing    # 函式層級耗時記錄器
from app.utils.app_logger import logger
import copy

class HybridSQLBuilder:
    def __init__(self):
        #  定義靜態的映射表 
        # 用於SELECT子句
        # 輸出的JSON內容的鍵值也會照這個映射表生內容
        self.field_mapping = {
            "id": "p.id", 
            "restaurant_name": "p.name", 
            "address": "p.address", 
            "rating": "p.rating",
            "phone": "p.phone",       
            "website": "p.website",
            "opening_hours": "p.opening_hours",
            "user_ratings_total": "p.user_ratings_total",
            #"time": "p.opening_hours",             # 額外支援 time
            #"food_type": "pa.food_type",
            "cuisine_type": "pa.cuisine_type",
            "merchant_category": "pa.merchant_category",
            "facility_tags": "pa.facility_tags",
            "lat": "p.lat",
            "lng": "p.lng",
            #"dine_in": "pa.has_dine_in",
            #"air_conditioner": "pa.has_air_conditioner",
            #"takeout": "pa.has_takeout",
            #"all_you_can_eat": "pa.is_all_you_can_eat",
            #"private_parking": "pa.has_private_parking",
            #"mobile_payment": "pa.accept_mobile_payment",
            #"cash_only": "pa.accept_cash_payment",
            #"credit_card": "pa.accept_credit_card"
        }
        # 用於where子句
        # 如何篩選資料
        # 這裡必須對應到原始資料表的欄位
        # sql的執行順序是 where -> gourpby -> select
        self.sql_where_mapping = {
            "id": "p.id",
            "restaurant_name": "p.name",         
            "phone": "p.phone",       
            "website": "p.website",   
            "opening_hours": "p.opening_hours",
            "user_ratings_total": "p.user_ratings_total",
            "time": "p.opening_hours",             # 支援 logic_tree 傳入 time
            "address": "p.address", 
            "rating": "p.rating",
            "cuisine_type": "pa.cuisine_type",
            # "food_type": "pa.food_type",
            "merchant_category": "pa.merchant_category",
            "restaurant_type": "pa.merchant_category", # 依照要求：對應到類別
            
            # --- 設施與標籤映射 (中文 Key 由 AI 產出) ---
            "內用": "pa.has_dine_in",
            "冷氣": "pa.has_air_conditioner",
            "外帶": "pa.has_takeout",
            "吃到飽": "pa.is_all_you_can_eat",
            "特約停車場": "pa.has_private_parking"
        }
        # 定義哪些欄位屬於語意搜尋或模糊比對的範疇
        # 這裡的欄位是匯到向量資料庫去搜尋的欄位
        self.vector_fields = { "flavor", "review_summary", "cuisine_type"}
        self.facility_keys = {
            "內用", "冷氣", "外帶", "吃到飽", "特約停車場", 
            "行動支付", "現金支付", "信用卡" 
        }
        self.json_field_source = "pa.facility_tags"

    # 只負責看懂 JSON，告訴你需不需要跑向量搜尋
    # 解析意圖
    # 回傳一個字典,包含SQL所需的結構以及向量搜尋的需求
    def analyze_intent(self, json_input):
        s_id = json_input.get("s_id")
        # 記錄函式起始時間，用於計算整體意圖解析耗時
        # 為什麼放在 s_id 取得之後：s_id 是 logging 必要參數，取得後才有辦法完整記錄這筆計時
        t0_analyze = time.perf_counter()
        logger.info("[SQL Builder] 開始解析使用者意圖 (analyze_intent)")

        s_id = json_input.get("s_id")
        if not s_id:
            logger.error("[SQL Builder] 請求缺少 s_id，拒絕解析意圖")
            raise ValueError("Missing s_id: 多用戶環境下必須提供 Session ID")
        
        logger.info(f"[SQL Builder][SID: {s_id}] 開始解析使用者意圖")
        # 查詢用的json資料方便做處理
        plan = {
            "s_id": s_id,       # 用戶連線id
            "location_source": "none", # 新增：記錄來源 (user / default / none)
            "select_fields": [], # 預設一定查店家的id,name,address,rating欄位
            "sort_clauses": [],      # 存放 ORDER BY 的字串
            "sort_conditions": json_input.get("sort_conditions", []),
            "query_params": {},      # 預留給參數化查詢的字典  
            "page": json_input.get("page", 1),           # 記錄當前頁碼
            "page_size": json_input.get("page_size", 3), # 記錄每頁顯示幾筆
            "vector_needed": False,  # 是否需要去查向量資料庫
            "vector_keywords": {},    # 若需要，要查哪些關鍵字
            "photos_needed": False, # 是否有photo需求
            "distance_needed": False,
            "user_location": None
        }

        # 獲取使用者的經緯度
        user_loc = json_input.get("user_location")
        # 如果有[info_needed] = 包含distance需求或sort_condition有距離排序
        # 但沒有usder_location就先用預設的經緯度
        wants_distance = (
            "distance" in json_input.get("info_needed", []) or 
            any(s.get("field") == "distance" for s in json_input.get("sort_conditions", []))
        )
        # 3. 座標判斷邏輯
        if user_loc and "lat" in user_loc and "lng" in user_loc:
            # 狀況 A: 使用者提供了正確座標
            plan["location_source"] = "user"
            plan["distance_needed"] = True
            plan["user_location"] = user_loc
            logger.info(f"[SQL Builder][SID: {s_id}] 使用使用者提供座標: {user_loc}")
        elif wants_distance:
            # 狀況 B: 沒提供座標但功能需要距離，注入預設座標
            plan["location_source"] = "default"
            plan["distance_needed"] = True
            plan["user_location"] = {"lat": 22.9972300, "lng": 120.2522700}
            logger.warning(f"[SQL Builder][SID: {s_id}] 功能需要距離但未偵測到座標，注入崑山科大預設座標")
        else:
            # 狀況 C: 沒座標也沒距離需求
            plan["location_source"] = "none"
            plan["distance_needed"] = False

        # 取得意圖
        intent = json_input.get("main_intent", "query")
        logger.info(f"[SQL Builder][SID: {s_id}] 主意圖模式: {intent}")

        # 如果意圖的值為"recommend""
        if intent == "recommend":
            logger.info(f"[SQL Builder][SID: {s_id}] 進入推薦模式: 全選欄位並強制開啟照片")
            # 推main_intent如果等於("recommand")無視info_needed,直接選擇所有欄位
            for key, db_col in self.field_mapping.items():
                plan["select_fields"].append(f"{db_col} AS {key}")

            # 推薦模式強制開啟照片提供功能
            plan["photos_needed"] = True
        
        else:
            # query一般查詢模式
            base_fields = {
                "id": "p.id",
                "restaurant_name": "p.name", # 強制回傳名稱
                "address": "p.address",
                "rating": "p.rating",
                "reviews_count": "p.user_ratings_total",
                "facility_tags": "pa.facility_tags",
                "lat": "p.lat",  # 確保後端計算距離永遠有資料
                "lng": "p.lng"   # 確保後端計算距離永遠有資料
            }
            
            for key, db_col in base_fields.items():
                plan["select_fields"].append(f"{db_col} AS {key}")

            # 加入使用者在 info_needed 指定的額外欄位
            for info in json_input.get("info_needed",[]):
                # 處理照片需求
                if info == "photos":
                    plan["photos_needed"] = True

                # 處理距離需求
                if info == "distance" and user_loc:
                    # distance是動態生成的
                    continue
                
                # 處理一般欄位
                if info in self.field_mapping:
                    col_sql = f"{self.field_mapping[info]} AS {info}"
                    # 防止重複加入 (例如 name 已經在預設欄位裡了)
                    if col_sql not in plan["select_fields"]:
                        plan["select_fields"].append(col_sql)

                

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
    

    # 遞迴掃描邏輯樹，提取向量關鍵字
    def _scan_for_vector_intent(self, node, plan, s_id):
        if not node: return
        
        if "conditions" in node:
            for child in node["conditions"]:
                self._scan_for_vector_intent(child, plan, s_id)
        else:
            key = list(node.keys())[0]
            val = node[key].get("value")
            if val is None: return

            # 處理值，轉為字串
            if isinstance(val, list):
                processed_val = " ".join([str(i) for i in val])
            else:
                processed_val = str(val)
            
            hybrid_fields = {"food_type", "cuisine_type", "flavor", "facility_tags", "service_tags"}
            
            if key in self.vector_fields or key in hybrid_fields:
                # --- 修改開始：改用 List 儲存以防覆蓋 ---
                if key not in plan["vector_keywords"]:
                    plan["vector_keywords"][key] = []
                
                # 如果該 key 本來不是 list (為了相容舊邏輯)，強轉成 list
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
        s_id = plan.get("s_id")
        # 記錄 SQL 建構起始時間，涵蓋 _strip_strict_conditions 與 _recursive_parse 的整體耗時
        # 為什麼不對遞迴子函式個別計時：子函式會被呼叫多次，個別計時會產生大量噪音列，不利分析
        t0_build_sql = time.perf_counter()
        logger.info(f"[SQL Builder][SID: {s_id}] 開始建構主查詢 SQL")

        logic_tree = copy.deepcopy(plan.get("raw_logic_tree", {}))

        # 如果進入降階模式，執行「條件脫殼」
        if is_fallback:
            logger.info(f"[SQL Builder][SID: {s_id}] 偵測到 Fallback 模式，開始放寬 SQL 過濾條件")
            logic_tree = self._strip_strict_conditions(logic_tree)

        # 1. 初始化分頁變數
        page = plan.get("page", 1)
        page_size = plan.get("page_size", 3)
        offset = (page - 1) * page_size

        # 2. 重置計數器與參數字典，確保每次生成 SQL 都是從 p0 開始
        self.param_counter = 0 
        self.query_params = {} 

        # 3. 遞迴生成 WHERE 子句
        # 產生的參數會存入 self.query_params，計數器會增加
        where_sql = self._recursive_parse(logic_tree, s_id)
        plan["_cached_where"] = where_sql # 暫存起來
        plan["_cached_params"] = copy.deepcopy(self.query_params)

        # 將產生的中間結果存回 plan 供除錯與 diagnostics 使用
        plan["generated_where_clause"] = where_sql
        plan["query_params"] = self.query_params

        final_where = []
        if where_sql:
            final_where.append(where_sql)

        if plan.get("distance_needed") and plan.get("user_location"):
            u_lat = plan["user_location"]["lat"]
            u_lng = plan["user_location"]["lng"]
            dist_sql = get_haversine_distance_sql(u_lat, u_lng)
            dist_alias = f"{dist_sql} AS distance"
            if not any("AS distance" in f for f in plan["select_fields"]):
                plan["select_fields"].append(dist_alias)

        # 6. 組裝最終 SQL
        sql = "SELECT " + ", ".join(plan["select_fields"])
        sql += " FROM all_places p "
        sql += " LEFT JOIN Place_Attributes as pa ON p.id = pa.place_id"
        
        if final_where:
            sql += " WHERE " + " AND ".join(final_where)
        
        # 必須依據 ID 分組以支援聚合欄位
        sql += " GROUP BY p.id "


        # 判斷是否需要擴大取樣：檢查是否開啟了延遲排序旗標
        is_deferred = plan.get("deferred_sorting", False)

        if not is_deferred:
            # A. 正常 SQL 模式：由資料庫精確分頁
            if plan.get("sort_clauses"):
                sql += " ORDER BY " + ", ".join(plan["sort_clauses"])
            sql += f" LIMIT {page_size} OFFSET {offset}"
            logger.info(f"[SQL Builder] 正常分頁模式: LIMIT {page_size}")
        else:
            # B. 向量模式：取消 SQL 排序，直接抓出 100 筆候選店家供向量重排
            sql += " ORDER BY p.rating DESC, p.user_ratings_total DESC "
            sql += "LIMIT 150"
            logger.info(f"[SQL Builder] 語意重排模式: 擴大取樣 150 筆優質候選店家")

        # 記錄 build_sql 函式總耗時至 CSV
        log_function_timing("build_sql", s_id, time.perf_counter() - t0_build_sql)

        return sql, self.query_params
            

    def _strip_strict_conditions(self, node):
        """
        因為設施與類型已全數移往向量搜尋，
        SQL Builder 的放寬邏輯僅針對 SQL 實體欄位（如評分、區域）。
        """
        if not node:
            return node
        
        # 處理邏輯群組 (AND/OR)
        if "conditions" in node:
            # 定義降階時要「犧牲」的 SQL 實體欄位
            # 這裡不再包含 '冷氣'、'內用' 等，因為它們在 SQL 階段會被 _recursive_parse 攔截
            sql_strict_keys = {"rating", "user_ratings_total", "address"}
            
            new_conditions = []
            for child in node["conditions"]:
                # 取得葉節點的 Key
                child_key = list(child.keys())[0] if "conditions" not in child else None
                
                # 如果是 SQL 實體欄位且需要放寬
                if child_key and child_key in sql_strict_keys:
                    logger.info(f"[SQL Builder] Fallback：放寬 SQL 實體過濾條件 '{child_key}'")
                    continue
                
                # 遞迴處理
                if "conditions" in child:
                    processed_child = self._strip_strict_conditions(child)
                    if processed_child and len(processed_child.get("conditions", [])) > 0:
                        new_conditions.append(processed_child)
                else:
                    new_conditions.append(child)
            
            node["conditions"] = new_conditions
            return node
            
        return node

    # 將巢狀JSON邏輯樹轉平為SQL WHERE字串
    def _recursive_parse(self, node, s_id):
        if not node: 
            logger.debug("[SQL Builder Debug] 節點為空，跳過解析")
            return None
        
        key = list(node.keys())[0]
        vector_only_fields = {
            "service_tags", "food_type", "cuisine_type",
            "內用", "冷氣", "外帶", "吃到飽", "特約停車場", "行動支付", "現金支付", "信用卡"
        }
        if key in vector_only_fields:
            logger.info(f"[SQL Builder][SID: {s_id}] 攔截向量欄位 '{key}'，不生成 SQL")
            return None

        # 處理邏輯運算子節點 (AND/OR)
        # 此區塊負責處理帶有子條件列表 (conditions) 的複合邏輯節點
        if "op" in node and "conditions" in node:
            operator = node["op"].upper() # 取得運算子 (如 'and', 'or') 並轉大寫以符合 SQL 標準
            logger.debug(f"[SQL Builder Debug] 解析群組節點: {operator}, 子條件數: {len(node['conditions'])}")
            child_sqls = []
            # 遍歷所有子條件，進行遞迴解析
            for i, child in enumerate(node["conditions"]):
                # 【遞迴呼叫】繼續往深處解析，直到遇到葉節點 (實際的欄位比較)
                child_sql = self._recursive_parse(child, s_id)
                # 如果該子條件產生了有效的 SQL 片段 (非向量欄位或空值)，則加入清單
                if child_sql:
                    child_sqls.append(child_sql)
                else:
                    logger.debug(f"[SQL Builder Debug] 群組 {operator} 的第 {i} 個子條件解析結果為空")
            # 安全檢查：如果該群組內所有子條件解析後都沒有結果，則回傳 None 讓上層跳過此群組
            if not child_sqls: 
                logger.debug(f"[SQL Builder Debug] 群組 {operator} 無任何有效子條件")
                return None
            # 如果群組內只有一個有效條件，就不需要額外包覆括號與運算子
            if len(child_sqls) == 1: 
                return child_sqls[0]
            # 使用目前的運算子 (AND/OR) 串接所有子片段，並用括號封裝以確保運算優先權正確
            # 例如: (p.rating > 4.5 OR p.address LIKE '%永康%')
            separator = f" {operator} "  
            combined_sql = f"({separator.join(child_sqls)})"
            logger.debug(f"[SQL Builder Debug] 組合群組 SQL: {combined_sql}")
            return combined_sql

        # 2. 處理單一條件 (葉節點)
        # 取得當前條件的 Key (例如: "外帶" 或 "food_type")
        
        node_data = node[key]
        val = node_data.get("value")
        cmp = node_data.get("cmp", "=").upper()

        logger.info(f"[SQL Builder][SID: {s_id}] ===> [Recursive Parse] 處理欄位: '{key}' | 算符: {cmp}")

        # 只要 val 是只有一個元素的 list，不管 cmp 是什麼，先把它轉成純字串/數值
        # 這樣後續不論走 IN 還是 LIKE 邏輯，item 都會是乾淨的
        if isinstance(val, list) and len(val) == 1:
            val = val[0]
        
        # 核心追蹤
        logger.info(f"===> [Recursive Parse] 處理欄位: '{key}' | 算符: {cmp} | 原始值: {val}")

        # 優先檢查向量欄位
        if key in self.vector_fields:
            logger.debug(f"[SQL Builder][SID: {s_id}] '{key}' 為向量欄位，跳過 SQL 生成")
            return None

        # 處理 JSON 設施標籤
        if key in self.facility_keys:
            if val is not True:
                logger.debug(f"[SQL Builder][SID: {s_id}] 生成設施標籤 SQL 片段: {key}")
                return None
            # 從 sql_where_mapping 取得對應的新欄位名 (如 pa.has_air_conditioner)
            db_col = self.sql_where_mapping.get(key)
            if not db_col: return None
            p_name = f"p{self.param_counter}"
            # 數值改為 1 (TINYINT 1 代表 True)
            self.query_params[p_name] = 1
            self.param_counter += 1
            # 生成精確比對 SQL: "pa.has_air_conditioner = 1"
            sql_fragment = f"{db_col} = %({p_name})s"
            logger.debug(f"[SQL Builder] 生成精確設施 SQL: {sql_fragment}")
            return sql_fragment
        
        # --- 處理一般 SQL 欄位 ---
        if key in self.sql_where_mapping:
            db_col = self.sql_where_mapping[key]
            # 注意：這裡先不要宣告 p_name，交給各分支處理 counter

            # 定義哪些欄位要走 Full-Text 搜尋 (建議 address 和 restaurant_name)
            fulltext_fields = ["address", "restaurant_name"]
            fields_to_force_like = ["restaurant_type", "merchant_category"]
            

            # 確保 val 只要是單一元素的 list 就轉成純字串
            safe_val = val[0] if isinstance(val, list) and len(val) == 1 else val

            # 1. 新增：處理 Full-Text 搜尋
            if key in fulltext_fields:
                p_name = f"p{self.param_counter}"
                self.query_params[p_name] = safe_val  # 不需要加 % 號
                self.param_counter += 1
                
                # 使用 MATCH AGAINST 語法
                # IN NATURAL LANGUAGE MODE 是最直覺的搜尋方式
                sql_fragment = f"MATCH({db_col}) AGAINST(%({p_name})s IN NATURAL LANGUAGE MODE)"
                
                logger.info(f"[SQL Builder] 生成 Full-Text SQL: {sql_fragment} | 關鍵字: {safe_val}")
                return sql_fragment

            # 強制模糊比對欄位
            # 只要在名單內，不管 AI 給什麼 cmp，一律強制轉 LIKE
            elif key in fields_to_force_like or cmp == "LIKE":
                p_name = f"p{self.param_counter}"
                param_value = f"{safe_val}%" # 此時 safe_val 已經是 '崑大路'
                self.query_params[p_name] = param_value
                self.param_counter += 1
                sql_fragment = f"{db_col} LIKE %({p_name})s"
                logger.debug(f"[SQL Builder Debug] 生成強制模糊 SQL: {sql_fragment} | {p_name}: {param_value}")
                return sql_fragment

            # 處理真正的集合查詢 (IN)
            elif cmp in ["in", "not in"]:
                val_list = val if isinstance(val, list) else [val]
                p_names = []
                for item in val_list:
                    current_p = f"p{self.param_counter}"
                    self.query_params[current_p] = item
                    p_names.append(f"%({current_p})s")
                    self.param_counter += 1
                param_placeholders = ", ".join(p_names)
                sql_fragment = f"{db_col} {cmp} ({param_placeholders})"
                logger.debug(f"[SQL Builder Debug] 生成集合 SQL: {sql_fragment}")
                return sql_fragment
            
            # 一般精確比對
            else:
                p_name = f"p{self.param_counter}"
                self.query_params[p_name] = safe_val
                self.param_counter += 1
                sql_fragment = f"{db_col} {cmp} %({p_name})s"
                logger.debug(f"[SQL Builder Debug] 生成一般 SQL: {sql_fragment}")
                return sql_fragment
        
        # 欄位未定義
        logger.warning(f"!!! [SQL Builder Warning] 欄位 '{key}' 找不到對應的 Mapping 配置，該條件被丟棄")
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
    
    