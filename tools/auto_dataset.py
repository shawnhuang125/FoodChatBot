import json
import random
import os
import string
import argparse
import inspect
from dotenv import load_dotenv
from dataset_manifest import SCENARIO_TEMPLATES
# 從 manifest 導入設定
from dataset_manifest import VOCAB, FIELD_SPECS, FIELD_MENU, SORT_OPTIONS, TASK_PROMPTS, NLG_TEMPLATES, SLOT_FILLING_PHRASES, CHATTER_VOCAB

# 載入 .env 檔案
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

# =====================================================================
# [區塊 1] 系統設定
# =====================================================================
# 從 .env 讀取設定
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SHUFFLE_SEED = int(os.getenv("FT_SHUFFLE_SEED", 42))

# 設定隨機種子以確保可複現性
random.seed(SHUFFLE_SEED)

# =====================================================================
# [區塊 1.5] 自動化輸入模擬器 (支援 --sequence)
# =====================================================================
def consume_input(prompt_text, seq_iter=None):
    if seq_iter is not None:
        try:
            val = next(seq_iter)
            print(f"{prompt_text}{val} (自動填入)")
            return str(val).strip()
        except StopIteration:
            pass
    try:
        return input(prompt_text).strip()
    except EOFError:
        return ""

# =====================================================================
# [區塊 2] 核心邏輯積木與工具
# =====================================================================
def leaf(field, val, resolved=True):
    cmp_op = "="
    if field in FIELD_SPECS and "cmp" in FIELD_SPECS[field]:
        cmp_op = FIELD_SPECS[field]["cmp"]
    elif field == "rating": 
        cmp_op = ">="
        
    node = {field: {"cmp": cmp_op, "value": [val]}}
    if not resolved:
        node[field]["resolved"] = False
    return node

def AND(*conditions):
    return {"op": "AND", "conditions": list(conditions)}

def OR(*conditions):
    return {"op": "OR", "conditions": list(conditions)}

def get_text(field, val):
    return random.choice(FIELD_SPECS[field]["tmpl"]).format(val=val)

def ask_fields(prompt_text, hint="12", seq_iter=None):
    print("\n  [1] 地址(address)  [2] 食物(food_type)    [3] 評分(rating)   [4] 時間(time)")
    print("  [5] 服務(service_tags) [6] 口味(flavor) [7] 菜系(cuisine)")
    
    f_choice = consume_input(f"  {prompt_text} (輸入代號如 {hint}): ", seq_iter)
    if not f_choice: f_choice = hint[0] 
    return [FIELD_MENU[char] for char in f_choice if char in FIELD_MENU]

def build_intent_json(intent, logic_tree=None, need_time=False, info_needed=None, follow_up=False, sort_conditions=None, page=None, query_id=None):
    data = {"main_intent": intent}
    
    if intent == "fetch_more":
        if follow_up:
            data["follow_up"] = True
            return data
        data["page"] = page if page else 2
        data["query_id"] = query_id
        return data

    data["follow_up"] = True if follow_up else None
    data["need_time"] = True if need_time else None
    data["info_needed"] = info_needed if info_needed else None
    data["logic_tree"] = logic_tree

    if intent in ["recommend", "query"]:
        if page is not None:
            data["page"] = page
        else:
            data["page"] = None if follow_up else 1
        data["sort_conditions"] = sort_conditions if sort_conditions else [{"field": "rating", "method": "DESC"}]
        data["query_id"] = query_id
    else:
        data["page"] = None 
        
    return {k: v for k, v in data.items() if v is not None}

def package_to_entry(*args, task=None):
    """
    🎯 萬能包裝器：修復 dict 轉 json 爆開的問題，完美支援 Task 1, 2, 3
    """
    prompts = {1: TASK_PROMPTS["task1"], 2: TASK_PROMPTS["task2"], 3: TASK_PROMPTS["task3"]}
    sys_prompt = prompts.get(task, TASK_PROMPTS["task1"])

    # 🔥 加入這一行：處理 TASK_PROMPTS 中的多餘換行與排版縮進
    sys_prompt = inspect.cleandoc(sys_prompt)

    if len(args) == 1 and isinstance(args[0], list):
        messages = args[0]
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = sys_prompt
        else:
            messages.insert(0, {"role": "system", "content": sys_prompt})
        return {"messages": messages}
        
    elif len(args) == 2:
        user_text, assistant_content = args
        # 🎯 防爆點：如果傳進來的 assistant 已經是字串(Task 3)，就不要再 dumps！
        if isinstance(assistant_content, dict):
            assistant_content = json.dumps(assistant_content, ensure_ascii=False, separators=(",", ":"))
        return {
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_content}
            ]
        }
        
    elif len(args) == 3:
        user_text, assistant_dict, assistant_1_text = args
        assistant_str = json.dumps(assistant_dict, ensure_ascii=False, separators=(",", ":")) if isinstance(assistant_dict, dict) else assistant_dict
        return {
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_str},
                {"role": "assistant 1", "content": assistant_1_text}
            ]
        }
    return {}

# =====================================================================
# [區塊 3] 🍽️ 推薦意圖 (Recommend) 專屬生產線
# =====================================================================
class RecommendBuilder:

    @classmethod
    def _build_template_node(cls, depth=1, seq_iter=None):
        indent = "  " * depth
        print(f"\n{indent}📍 [第 {depth} 層] 請選擇此節點的邏輯類型:")
        print(f"{indent}[1] 單一維度 (葉節點，如: 地點、食物...)")
        print(f"{indent}[2] AND 組合 (且 / 同時滿足)")
        print(f"{indent}[3] OR 組合 (或 / 擇一即可)")
        
        choice = consume_input(f"{indent}👉 輸入 (1/2/3): ", seq_iter)
        
        if choice == '1':
            fields = ask_fields(f"請輸入 1 個維度代號 (只需1個)", hint="1", seq_iter=seq_iter)
            field = fields[0] if fields else "food_type" 
            return {"type": "leaf", "field": field}
            
        elif choice in ['2', '3']:
            op_type = "AND" if choice == '2' else "OR"
            count_str = consume_input(f"{indent}👉 請問這個 {op_type} 組合包含幾個子條件？(預設 2): ", seq_iter)
            count = int(count_str) if count_str.isdigit() and int(count_str) > 1 else 2
            
            children = []
            for i in range(count):
                print(f"\n{indent}🔹 開始設定 {op_type} 的第 {i+1} 個子條件...")
                children.append(cls._build_template_node(depth + 1, seq_iter))
                
            return {"type": op_type, "children": children}
        else:
            print(f"{indent}❌ 無效選擇，預設為單一食物維度。")
            return {"type": "leaf", "field": "food_type"}

    @classmethod
    def _instantiate_template(cls, node):
        if node["type"] == "leaf":
            field = node["field"]

            if field == "rating":
                val = random.choice(VOCAB["rating"])
                cmp_symbol = random.choice(list(FIELD_SPECS["rating"]["ops"].keys()))
                tmpl = random.choice(FIELD_SPECS["rating"]["ops"][cmp_symbol])
                text = tmpl.format(val=val)
                logic = {"rating": {"cmp": cmp_symbol, "value": [val]}}
                return text, logic, False

            val = random.choice(VOCAB[field])
            
            if field == "address" and random.random() > 0.5:
                val2 = random.choice(VOCAB["address"])
                combined_val = f"{val2}{val}"
                text = get_text(field, combined_val) 
                logic = AND(leaf("address", val2), leaf("address", val))
                return text, logic, False

            text = get_text(field, val)
            return text, leaf(field, val), (field == "time")
            
        elif node["type"] == "AND":
            if len(node["children"]) == 2:
                c1, c2 = node["children"][0], node["children"][1]
                is_distributive = (c1["type"] == "leaf" and c2["type"] == "OR") or \
                                  (c2["type"] == "leaf" and c1["type"] == "OR")
                
                if is_distributive:
                    leaf_node = c1 if c1["type"] == "leaf" else c2
                    or_node = c2 if c2["type"] == "OR" else c1
                    
                    if all(c["type"] == "leaf" for c in or_node["children"]):
                        leaf_t, leaf_l, nt1 = cls._instantiate_template(leaf_node)
                        or_texts, or_logics = [], []
                        for c in or_node["children"]:
                            t, l, nt2 = cls._instantiate_template(c)
                            or_texts.append(t.rstrip("的")) 
                            or_logics.append(l)
                            nt1 = nt1 or nt2
                            
                        connector = random.choice(["或是", "或者是", "還是"])
                        text = f"{leaf_t}{connector.join(or_texts)}" 
                        return text, AND(leaf_l, OR(*or_logics)), nt1

            texts, logics, need_t = [], [], False
            for child in node["children"]:
                t, l, nt = cls._instantiate_template(child)
                texts.append(t)
                logics.append(l)
                need_t = need_t or nt
            
            if all(c["type"] == "leaf" for c in node["children"]):
                base_texts = [t.rstrip("的") for t in texts]
                pattern_type = random.choice(["simple", "emphasis", "natural", "descriptive"])
                if pattern_type == "simple":
                    c = random.choice(["、", "，而且要", "，還有", " "])
                    text = c.join(base_texts[:-1]) + "的" + base_texts[-1]
                elif pattern_type == "emphasis":
                    text = f"{texts[0]}，最好是{'、'.join(texts[1:])}"
                elif pattern_type == "natural":
                    c = random.choice(["、", "，還要"])
                    text = f"{base_texts[0]}，然後要有{c.join(texts[1:])}" if len(base_texts) > 1 else texts[0]
                else:
                    text = "又要".join([""] + texts) 
            else:
                c = random.choice(["，除此之外還要", "，而且還要", "，同時也要滿足"])
                text = c.join(texts)
            return text, AND(*logics), need_t
            
        elif node["type"] == "OR":
            texts, logics, need_t = [], [], False
            for child in node["children"]:
                t, l, nt = cls._instantiate_template(child)
                texts.append(t)
                logics.append(l)
                need_t = need_t or nt
            
            has_complex_child = any(c["type"] != "leaf" for c in node["children"])
            
            if has_complex_child:
                text = random.choice([
                    "要嘛是「" + "」，不然就是「".join(texts) + "」",
                    "看是要「" + "」還是「".join(texts) + "」都可以"
                ])
            else:
                text = "看是" + "還是".join(texts) + "都可以"
                
            return text, OR(*logics), need_t

    @classmethod
    def universal_dynamic_builder(cls, seq_iter=None, override_count=None):
        print("\n 🛠️ 開始建構【萬能邏輯樹】(若只要單一條件，首層請直接選 1)...")
        template = cls._build_template_node(depth=1, seq_iter=seq_iter)
        
        print("\n  📍 [排序設定] 請選擇這批資料的排序方式:")
        print("  [0] 🎲 隨機混搭 (系統每次自動隨機挑選不同的排序與修飾詞)")
        for i, opt in enumerate(SORT_OPTIONS):
            desc = opt['text_modifier'] if opt['text_modifier'] else "無修飾詞 (隱含評分最高)"
            sort_field = opt['sort'][0]['field']
            sort_method = opt['sort'][0]['method']
            print(f"  [{i+1}] {desc} -> ({sort_field} {sort_method})")
            
        sort_input = consume_input("  👉 請輸入代號 (預設 0): ", seq_iter)
        
        if override_count is not None:
            generate_count = override_count
            print(f"\n👉 藍圖建構完成！請問要根據此架構產生幾筆資料？(預設 10): {generate_count} (由參數自動指定)")
        else:
            count_str = consume_input("\n👉 藍圖建構完成！請問要根據此架構產生幾筆資料？(預設 10): ", seq_iter)
            generate_count = int(count_str) if count_str.isdigit() and int(count_str) > 0 else 10
        
        dataset = []
        for _ in range(generate_count):
            text, logic, need_time = cls._instantiate_template(template)
            
            if sort_input.isdigit() and 1 <= int(sort_input) <= len(SORT_OPTIONS):
                sort_choice = SORT_OPTIONS[int(sort_input) - 1]
            else:
                sort_choice = random.choice(SORT_OPTIONS)
                
            sort_txt = sort_choice["text_modifier"]
            final_text = f"幫我找{sort_txt}{text}"
            
            dataset.append(package_to_entry(
                final_text, 
                build_intent_json(
                    intent="recommend", 
                    logic_tree=logic, 
                    need_time=need_time, 
                    sort_conditions=sort_choice["sort"]
                ),
                task=1
            ))
        return dataset

# =====================================================================
# [區塊 4] 🔍 查詢意圖 (Query) 專屬生產線
# =====================================================================
class QueryBuilder:

    @classmethod
    def universal_query_builder(cls, seq_iter=None, override_count=None):
        print("\n 🛠️ 開始建構【萬能複合查詢生產線】...")
        
        print("  📍 [對象設定] 請選擇查詢對象的類型:")
        print("  [1] 模糊代名詞 (這家/那間 -> 會自動設定 resolved: false)")
        print("  [2] 明確店名 (如: 鼎王/星巴克)")
        print("  [3] 複合過濾條件 (如: 永康區+火鍋 -> 進入動態邏輯樹)")
        target_choice = consume_input("  👉 輸入 (1/2/3): ", seq_iter)

        extra_filter_template = None
        if target_choice in ['1', '2']:
            print(f"\n  👉 是否要為對象加上額外過濾條件 (例如: 在永康區的...鼎王)？")
            print("  [0] 否 (直接查對象)  [1] 是 (進入邏輯樹建構器)")
            if consume_input("  👉 輸入 (0/1): ", seq_iter) == '1':
                extra_filter_template = RecommendBuilder._build_template_node(depth=1, seq_iter=seq_iter)

        template = None
        if target_choice == '3':
            template = RecommendBuilder._build_template_node(depth=1, seq_iter=seq_iter)

        print("\n  📍 [資訊設定] 請選擇要查詢的資訊欄位 (可多選):")
        print("  [1] 地址  [2] 電話  [3] 評論  [4] 距離  [5] 營業時間") # 🎯 移除 6 價位
        info_choice = consume_input("  👉 請輸入代號 (如 12 代表同時查地址與電話): ", seq_iter)
        
        info_map = {"1": "address", "2": "phone", "3": "reviews", "4": "distance", "5": "opening_hours"}
        selected_info_keys = [info_map[c] for c in info_choice if c in info_map]
        if not selected_info_keys: selected_info_keys = ["address"]

        if override_count is not None:
            generate_count = override_count
            print(f"\n👉 設定完成！請問要產生幾筆資料？(預設 10): {generate_count} (由參數自動指定)")
        else:
            count_str = consume_input("\n👉 設定完成！請問要產生幾筆資料？(預設 10): ", seq_iter)
            generate_count = int(count_str) if count_str.isdigit() and int(count_str) > 0 else 10

        dataset = []
        pronouns = ["這家", "那間", "這間", "他", "它", "那家餐廳"]
        
        for _ in range(generate_count):
            need_time = False
            is_fuzzy = False
            extra_text = "" 
            
            if target_choice == '1':
                filter_text = random.choice(pronouns)
                logic = leaf("restaurant_name", filter_text, resolved=False) 
                is_fuzzy = True
            elif target_choice == '2':
                filter_text = random.choice(VOCAB["store_name"])
                logic = leaf("restaurant_name", filter_text, resolved=True)
            else:
                filter_text, logic, need_time = RecommendBuilder._instantiate_template(template)

            if target_choice in ['1', '2'] and extra_filter_template:
                e_text, e_logic, e_time = RecommendBuilder._instantiate_template(extra_filter_template)
                extra_text = e_text
                need_time = need_time or e_time
                logic = AND(logic, e_logic)
            
            labels = []
            for k in selected_info_keys:
                label = [name for name, val in VOCAB["info"].items() if val == k][0]
                labels.append(label)
            
            if len(labels) == 1:
                text_labels_combined = labels[0]
            else:
                info_connector = random.choice(["跟", "與", "還有", "、"])
                text_labels_combined = "、".join(labels[:-1]) + f"{info_connector}{labels[-1]}"
            
            prefix = random.choice(["我想知道", "幫我查", "請問", "可以告訴我", "那", ""])
            
            if target_choice in ['1', '2']:
                text = f"{prefix}{extra_text}{filter_text}的{text_labels_combined}"
            else:
                turn_connector = random.choice(["，我想知道", "，那它的", "，幫我查", "的"])
                text = f"{filter_text}{turn_connector}{text_labels_combined}"
            
            dataset.append(package_to_entry(
                text,
                build_intent_json(
                    intent="query",
                    logic_tree=logic,
                    info_needed=selected_info_keys,
                    need_time=need_time,
                    follow_up=is_fuzzy 
                ),
                task=1
            ))
            
        return dataset

# =====================================================================
# [區塊 5] 🗣️ 閒聊與防禦意圖 (Chatter/Others) 專屬生產線
# =====================================================================
class ChatterBuilder:
    @classmethod
    def universal_chatter_builder(cls, seq_iter=None, override_count=None):
        print("\n 🛠️ 開始建構【萬能閒聊與防禦生產線】...")
        print("  📍 請選擇要產生的意圖類型 (可多選):")
        print("  [1] 問好  [2] 感謝  [3] 結束  [4] 未知/防禦")
        print("  [5] 開局直接換一批(防呆) 👑")
        choice = consume_input("  👉 請輸入代號 (可連打如 12345): ", seq_iter)

        intent_map = {"1": "greet", "2": "thanks", "3": "end", "4": "unknown", "5": "fetch_more_no_context"}
        selected_intents = [intent_map[c] for c in choice if c in intent_map]
        
        if not selected_intents:
            print("  ❌ 未選擇任何意圖。")
            return []

        if override_count is not None:
            num_per_intent = override_count
            print(f"\n👉 每個意圖要產生幾筆資料？(預設 10): {num_per_intent} (由參數自動指定)")
        else:
            count_str = consume_input("\n👉 每個意圖要產生幾筆資料？(預設 10): ", seq_iter)
            num_per_intent = int(count_str) if count_str.isdigit() and int(count_str) > 0 else 10

        dataset = []
        for intent in selected_intents:
            sentences = CHATTER_VOCAB.get(intent, ["..."])
            sampled_sentences = random.sample(sentences, min(len(sentences), num_per_intent)) if len(sentences) >= num_per_intent else random.choices(sentences, k=num_per_intent)

            for text in sampled_sentences:
                if intent == "fetch_more_no_context":
                    dataset.append(package_to_entry(text, build_intent_json("fetch_more", follow_up=True), task=1))
                else:
                    dataset.append(package_to_entry(text, build_intent_json(intent=intent, follow_up=True), task=1))
        
        return dataset

# =====================================================================
# [區塊 6] 👑 終極多輪對話生產引擎 (資料驅動版 Data-Driven Engine)
# =====================================================================
class MultiTurnBuilder:
    @staticmethod
    def generate_query_id():
        return f"{''.join(random.choices(string.ascii_uppercase, k=3))}-{''.join(random.choices(string.digits, k=4))}"

    @classmethod
    def _build_scenario_flow(cls, template_steps, ctx):
        """ [核心引擎] 根據 dataset_manifest.py 中定義的流程設定，動態渲染並組裝對話歷史 """
        messages = [{"role": "system", "content": TASK_PROMPTS["task1"]}]
        for step in template_steps:
            stype = step["type"]
            
            # --- 1. 變數渲染 ---
            user_text = step.get("user", "").format(**ctx) if step.get("user") else None
            sys_text = step.get("sys", "").format(**ctx) if step.get("sys") else None
            
            # --- 2. 邏輯樹提取與封裝 ---
            logic_key = step.get("logic")
            logic = ctx.get(logic_key) if logic_key in ctx else None
            resolved = step.get("resolved", True)
            
            # 若取出來的邏輯是一串字串 (如店名、代名詞)，則自動包裝為 leaf 葉節點
            if isinstance(logic, str):
                 logic = leaf("restaurant_name", logic, resolved=resolved)
            elif logic is None and isinstance(logic_key, str):
                 logic = leaf("restaurant_name", logic_key, resolved=resolved)
                 
            # --- 3. 準備 Intent 參數 ---
            intent_kwargs = {}
            if "page" in step:
                intent_kwargs["page"] = ctx.get(step["page"], step["page"])
            if "sort" in step:
                intent_kwargs["sort_conditions"] = ctx.get(step["sort"], {}).get("sort")
            if "q_id_ref" in step:
                intent_kwargs["query_id"] = ctx.get(step["q_id_ref"])
            if "info" in step:
                intent_kwargs["info_needed"] = [ctx.get(i, i) for i in step["info"]]
                
            # 🚨 [規範強制] resolved: false 必定要有 follow_up: true
            if step.get("follow_up") or not resolved:
                intent_kwargs["follow_up"] = True

            # --- 4. 裝載對話 ---
            if user_text:
                messages.append({"role": "user", "content": user_text})
            
            if stype == "greet":
                intent_json = build_intent_json("greet", follow_up=True)
            elif stype == "recommend":
                intent_json = build_intent_json("recommend", logic_tree=logic, **intent_kwargs)
            elif stype == "query":
                intent_json = build_intent_json("query", logic_tree=logic, **intent_kwargs)
            elif stype == "fetch_more":
                intent_json = build_intent_json("fetch_more", **intent_kwargs)
            elif stype == "thanks":
                intent_json = build_intent_json("thanks", follow_up=True)
            else:
                continue

            messages.append({"role": "assistant", "content": json.dumps(intent_json, ensure_ascii=False, separators=(",", ":"))})
            
            if sys_text:
                messages.append({"role": "assistant 1", "content": sys_text})
                
            if step.get("q_id"):
                messages.append({"role": "query_id", "content": ctx.get(step["q_id"], step["q_id"])})
                
        return messages

    @classmethod
    def generate_nuanced_data(cls, count=1000):
        dataset = []
        scenarios_to_run = list(range(1, 21)) if count == 20 else [random.randint(1, 20) for _ in range(count)]

        for scenario in scenarios_to_run:
            # 🛡️ 動態抽樣與語境構建 (Context Generation)
            addr_val = random.choice(VOCAB["address"])
            food_count = random.choices([1, 2, 3, 4], weights=[0.60, 0.25, 0.10, 0.05])[0]
            foods = random.sample(VOCAB["food_type"], k=food_count)
            
            if len(foods) == 1:
                food_logic = leaf("food_type", foods[0])
                food_text = foods[0]
            else:
                food_logic = OR(*[leaf("food_type", f) for f in foods])
                connector = random.choice(["或是", "還是", "或者是"])
                food_text = "、".join(foods[:-1]) + connector + foods[-1]
                
            t1_logic = AND(leaf("address", addr_val), food_logic)
            t1_text = f"在{addr_val}的{food_text}"
            
            ext_f_type = random.choice(["service_tags", "rating", "flavor"])
            ext_text, ext_logic, _ = RecommendBuilder._instantiate_template({"type": "leaf", "field": ext_f_type})

            stores = random.sample(VOCAB["store_name"], k=10) 
            info_k1 = random.choice(list(VOCAB["info"].keys())); info_v1 = VOCAB["info"][info_k1]
            info_k2 = random.choice([k for k in VOCAB["info"].keys() if k != info_k1]); info_v2 = VOCAB["info"][info_k2]

            sort = random.choice(SORT_OPTIONS)
            new_sort = random.choice([s for s in SORT_OPTIONS if s["text_modifier"] != ""])

            p1 = 1 if random.random() < 0.8 else random.randint(2, 5)
            new_food = random.choice([f for f in VOCAB["food_type"] if f not in foods])
            tag_val = random.choice(VOCAB["service_tags"])
            
            # 📦 將所有可能用到的佔位符與對應的邏輯包裝進 Context
            ctx = {
                "addr_val": addr_val,
                "food_text": food_text,
                "food_val": food_text,
                "t1_text": t1_text,
                "ext_text": ext_text,
                "new_food": new_food,
                "tag_val": tag_val,
                
                "t1_logic": t1_logic,
                "food_logic": food_logic,
                "ext_logic": ext_logic,
                "t1_logic_and_ext": AND(t1_logic, ext_logic),
                "addr_and_new_food": AND(leaf("address", addr_val), leaf("food_type", new_food)),
                "t1_logic_and_tag": AND(t1_logic, leaf("service_tags", tag_val)),
                "food_logic_and_ext": AND(food_logic, ext_logic),
                "addr_and_ext": AND(leaf("address", addr_val), ext_logic),
                "rating_45": leaf("rating", 4.5),
                
                "store_0": stores[0], "store_1": stores[1],
                "store_random_1": stores[2], "store_random_2": stores[3],
                "store_random_3": stores[4], "store_random_4": stores[5],
                "store_random_5": stores[6], "store_random_6": stores[7],
                "store_random_7": stores[8], "store_random_8": stores[9],
                
                "那間店": "那間店",
                "pronoun": random.choice(["這家", "那間", "這間店", "它"]),

                "info_k1": info_k1, "info_v1": info_v1,
                "info_k2": info_k2, "info_v2": info_v2,
                "reviews": VOCAB["info"]["評論"],
                
                "q_id_1": cls.generate_query_id(),
                "q_id_2": cls.generate_query_id(),
                "q_id_3": cls.generate_query_id(),

                "sort": sort,
                "new_sort": new_sort,
                "new_sort_text": new_sort["text_modifier"],

                "p1": p1, "p2": p1+1, "p3": p1+2, "p4": p1+3, "p5": p1+4,

                "greet_word": random.choice(CHATTER_VOCAB["greet"]),
                "thanks_word": random.choice(CHATTER_VOCAB["thanks"]),
                
                "fetch_more_word_1": random.choice(CHATTER_VOCAB["fetch_more_no_context"]),
                "fetch_more_word_2": random.choice(CHATTER_VOCAB["fetch_more_no_context"]),
                "fetch_more_word_3": random.choice(CHATTER_VOCAB["fetch_more_no_context"]),
                "fetch_more_word_4": random.choice(CHATTER_VOCAB["fetch_more_no_context"]),
                
                "res_text_1": random.choice(["沒問題，這是下一組名單：", "好的，再為您推薦幾間：", "請參考接下來的搜尋結果："]),
                "res_text_2": random.choice(["沒問題，這是下一組名單：", "好的，再為您推薦幾間：", "請參考接下來的搜尋結果："]),
                "res_text_3": random.choice(["沒問題，這是下一組名單：", "好的，再為您推薦幾間：", "請參考接下來的搜尋結果："]),
                
                "res_phrase_1": random.choice(["沒問題，為您更新推薦：", "好的，換一組給您選：", f"請參考第 {p1+1} 頁的結果：", "這幾家也不錯："]),
                "res_phrase_2": random.choice(["沒問題，為您更新推薦：", "好的，換一組給您選：", f"請參考第 {p1+2} 頁的結果：", "這幾家也不錯："]),
                "res_phrase_3": random.choice(["沒問題，為您更新推薦：", "好的，換一組給您選：", f"請參考第 {p1+3} 頁的結果：", "這幾家也不錯："]),
                "res_phrase_4": random.choice(["沒問題，為您更新推薦：", "好的，換一組給您選：", f"請參考第 {p1+4} 頁的結果：", "這幾家也不錯："]),

                "ext_user_prompt": random.choice([f"{ext_text}", f"我要{ext_text}的", f"那{ext_text}呢？"]),
                "back_phrase": random.choice(["我想看上一個條件的更多推薦", "回到最一開始那個搜尋，幫我換一批", "上上次找的那種還有其他的嗎"])
            }

            template = SCENARIO_TEMPLATES[scenario - 1]
            messages = cls._build_scenario_flow(template, ctx)
            dataset.append({"messages": messages})

        return dataset

# =====================================================================
# 🎯 新增區塊：Task 2 槽位補問生產線 (高多樣性動態版 🚀)
# =====================================================================
class SlotFillingBuilder:
    @classmethod
    def generate_data(cls, count=100):
        print(f"\n 🚀 正在生成 {count} 筆 Task 2 (多樣化句型補問) 資料...")
        dataset = []
        
        for _ in range(count):
            is_first_turn = random.choice([True, False])
            info_label = random.choice(list(VOCAB["info"].keys()))
            pronoun = random.choice(["這家", "那間", "這間店", "它", "這家餐廳", "那間店"])
            
            task1_json = {
                "main_intent": "query",
                "logic_tree": {"restaurant_name": {"cmp": "in", "value": [pronoun], "resolved": False}},
                "follow_up": True
            }

            if is_first_turn:
                user_text = f"{pronoun}的{info_label}是多少？"
                assistant_1_text = random.choice(SLOT_FILLING_PHRASES["first_turn"]).format(
                    pronoun=pronoun,
                    info_label=info_label
                )
                dataset.append(package_to_entry(user_text, task1_json, assistant_1_text, task=2))
            
            else:
                addr = random.choice(VOCAB["address"])
                food = random.choice(VOCAB["food_type"])
                stores = random.sample(VOCAB["store_name"], k=2)
                
                assistant_1_text = random.choice(SLOT_FILLING_PHRASES["multi_turn"]).format(
                    pronoun=pronoun,
                    info_label=info_label,
                    store_0=stores[0],
                    store_1=stores[1]
                )

                full_history = [
                    {"role": "system", "content": TASK_PROMPTS["task2"]},
                    {"role": "user", "content": f"幫我找{addr}的{food}"},
                    {"role": "assistant", "content": f"{{\"main_intent\":\"recommend\",\"logic_tree\":{{\"op\":\"AND\",\"conditions\":[{{\"address\":{{\"cmp\":\"in\",\"value\":[\"{addr}\"]}}}},{{\"food_type\":{{\"cmp\":\"=\",\"value\":[\"{food}\"]}}}}]}},\"page\":1}}"},
                    {"role": "assistant 1", "content": f"沒問題！這幾間不錯：1. {stores[0]} 2. {stores[1]}"},
                    {"role": "user", "content": f"那{pronoun}的{info_label}是多少？"},
                    {"role": "assistant", "content": json.dumps(task1_json, ensure_ascii=False, separators=(",", ":"))},
                    {"role": "assistant 1", "content": assistant_1_text}
                ]
                dataset.append({"messages": full_history})
            
        return dataset

# =====================================================================
# 🎯 新增區塊：Task 3 自然回話生產線 (加入 User 語境 + 專注評論摘要版 🚀)
# =====================================================================
class NLGBuilder:
    @classmethod
    def generate_data(cls, count=100):
        print(f"\n 🚀 正在生成 {count} 筆 Task 3 (加入 User 語境 & 卡片 UI 版) 資料...")
        dataset = []
        
        for _ in range(count):
            scenario = random.choices([1, 2, 3], weights=[0.4, 0.3, 0.3])[0]
            
            # 🎯 1. 決定品質狀態 (Quality State)
            status = random.choices(["success", "partial_success", "no_data"], weights=[0.4, 0.4, 0.2])[0]
            
            # 🎯 2. 同步技術欄位
            is_fallback = (status != "success")
            
            if status == "success":
                total_count = random.randint(5, 50)
                num_stores = min(total_count, random.randint(2, 3) if scenario == 1 else 1)
            elif status == "partial_success":
                total_count = random.randint(1, 3)
                num_stores = min(total_count, random.randint(1, 3) if scenario == 1 else 1)
            else:
                total_count = 0
                num_stores = 0
            
            location_source = random.choice(["user_provided", "device_gps", "fallback_default"])
            stores = random.sample(VOCAB["store_name"], k=num_stores) if num_stores > 0 else []
            
            needed_keys = {"restaurant_name", "review_summary", "ranking_reason", "hybrid_score"}
            info_label, info_key, tag = "", "", ""
            user_query_text = "" # 🎯 新增：模擬使用者的提問
            
            if scenario == 1:
                food = random.choice(VOCAB["food_type"])
                user_query_text = random.choice([f"我想吃{food}", f"附近有推薦的{food}嗎？", f"幫我找好吃的{food}"])
            elif scenario == 2:
                info_label = random.choice(list(VOCAB["info"].keys()))
                info_key = VOCAB["info"][info_label]
                needed_keys.add(info_key)
                target_store = stores[0] if stores else random.choice(VOCAB["store_name"])
                user_query_text = random.choice([f"{target_store}的{info_label}是多少？", f"那這間的{info_label}呢？", f"我想知道它的{info_label}"])
            elif scenario == 3:
                tag = random.choice(VOCAB["service_tags"])
                needed_keys.add("facility_tags")
                user_query_text = random.choice([f"要有{tag}的喔", f"幫我找有提供{tag}的店", f"那有{tag}的餐廳嗎？"])

            final_results = []
            if status != "no_data":
                for name in stores:
                    res_name = name
                    
                    rev_frag = random.choice(VOCAB["review_fragments"])
                    rev_text = "，".join(random.sample(rev_frag, k=2))
                    
                    store_data = {
                        "restaurant_name": res_name,
                        "review_summary": rev_text,
                        "ranking_reason": random.choice(VOCAB["ranking_reasons"]),
                        "hybrid_score": round(random.uniform(0.75, 0.98), 4)
                    }
                    
                    if "cuisine_type" in needed_keys: store_data["cuisine_type"] = random.choice(VOCAB["cuisine"])
                    if "rating" in needed_keys: store_data["rating"] = random.choice(VOCAB["rating"])
                    if "phone" in needed_keys: store_data["phone"] = f"06-{random.randint(2000000, 3999999)}"
                    if "opening_hours" in needed_keys: store_data["opening_hours"] = random.choice(VOCAB["hours"])
                    if "facility_tags" in needed_keys: store_data["facility_tags"] = ["內用", tag if scenario == 3 else "冷氣"]
                    
                    final_results.append(store_data)

            # 🎯 3. 按照 API 範例構造巢狀字典
            task3_input_data = {
                "search_metadata": {
                    "status": status,
                    "is_fallback": is_fallback,
                    "ai_behavior_hint": random.choice(VOCAB["AI_HINTS"][status]),
                    "search_status": {
                        "total_count": total_count,
                        "location_info": {"source": location_source}
                    }
                },
                "restaurants": final_results
            }

            # 🎯 4. 因果一致性語法樹生成
            intro = random.choice(NLG_TEMPLATES["intro"][status])
            
            if location_source == "fallback_default":
                intro = f"因為目前不確定妳的確切位置，所以先用預設中心幫妳找。{intro}"
            if total_count > 10 and status == "success":
                intro += f" 這次搜尋結果超豐富，總共有 {total_count} 家符合條件喔！"

            blocks = []
            if status != "no_data":
                for res in final_results:
                    r_name = res['restaurant_name']
                    review_focus = res['review_summary']
                    
                    if scenario == 2:
                        val = res.get(info_key, "查無資料")
                        desc = random.choice(NLG_TEMPLATES["scenario_2"]).format(info_label=info_label, val=val, review_focus=review_focus)
                    elif scenario == 3:
                        desc = random.choice(NLG_TEMPLATES["scenario_3"]).format(tag=tag, review_focus=review_focus)
                    else: 
                        desc = random.choice(NLG_TEMPLATES["scenario_1"]).format(review_focus=review_focus)
                    
                    # 確保 50 字內
                    if len(desc) > 50:
                        desc = desc[:47] + "..."
                    
                    blocks.append(f"<start>{r_name}： {desc} <end>")
            
            blocks_text = "\n".join(blocks)

            outro_type = "no_results" if status == "no_data" else "normal"
            outro = random.choice(NLG_TEMPLATES["outro"][outro_type])
            
            ans_text = f"{intro}\n{blocks_text}\n\n{outro}" if blocks_text else f"{intro}\n\n{outro}"
            
            # 🎯 傳入三個參數：User提問, JSON資料, 最終推坑文
            dataset.append(package_to_entry(user_query_text, task3_input_data, ans_text, task=3))
            
        return dataset
# =====================================================================
# [區塊 7] 路由器與主引擎
# =====================================================================
RECOMMEND_ROUTES = {
    "1": ("【萬能推薦引擎】動態建構邏輯樹 (包含單一與無限層巢狀 👑)", RecommendBuilder.universal_dynamic_builder),
}

QUERY_ROUTES = {
    "1": ("【萬能複合查詢】支援動態過濾(地點/種類) + 多重資訊查詢 👑", QueryBuilder.universal_query_builder),
}

CHATTER_ROUTES = {
    "1": ("【萬能閒聊引擎】(強制帶入 follow_up: true 👑)", ChatterBuilder.universal_chatter_builder),
}

def show_sub_menu(title, routes, seq_iter=None, override_count=None):
    print(f"\n  --- {title} 生產線 ---")
    for key, (desc, func) in routes.items():
        print(f"  [{key}] {desc}")
    print("  [b] 返回主選單")
    
    choice = consume_input("  👉 請選擇細項生產線: ", seq_iter)
    
    if choice in routes:
        desc, func = routes[choice]
        print(f"\n  🚀 正在設定: {desc}...")
        return func(seq_iter=seq_iter, override_count=override_count) 
    elif choice.lower() == 'b':
        return None
    else:
        print("  ❌ 無效的選擇。")
        return None

def save_data(final_data, output_path):
    if not final_data:
        print("\n❌ 未產生任何資料 (可能未選擇維度或處於 pass 狀態)。")
        return
        
    existing_data = []
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except: pass
        
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(existing_data + final_data, f, ensure_ascii=False, indent=2)
        
    print(f"\n✨ 任務完成！成功新增 {len(final_data)} 筆資料。")
    print(f"📂 目前累積總數：{len(existing_data) + len(final_data)} 筆")
    print(f"💾 檔案已儲存至：{output_path}")

def main():
    parser = argparse.ArgumentParser(description="資料集自動化產生器")
    parser.add_argument("--output", type=str, help="指定輸出的 JSON 檔案完整路徑")
    parser.add_argument("--mode", type=str, choices=["A", "B", "C", "D", "E", "F"], help="執行模式")
    parser.add_argument("--count", type=int, help="生成數量")
    parser.add_argument("--sequence", type=str, help="Task 1 自動化序列，逗號分隔 (例: 1,1,2,0)")
    args = parser.parse_args()

    if args.output:
        final_output_path = os.path.abspath(args.output)
    else:
        env_path = os.getenv("FT_GENERATOR_OUTPUT_FILE", "dataset/auto_dataset.json")
        final_output_path = os.path.join(PROJECT_ROOT, env_path)

    # =========================================================
    # CLI 自動調度模式
    # =========================================================
    if args.mode:
        seq_iter = iter(args.sequence.split(",")) if args.sequence else None
        final_data = None
        
        if args.mode == 'A':
            final_data = show_sub_menu("🍽️ 推薦 (Recommend)", RECOMMEND_ROUTES, seq_iter, args.count)
        elif args.mode == 'B':
            final_data = show_sub_menu("🔍 查詢 (Query)", QUERY_ROUTES, seq_iter, args.count)
        elif args.mode == 'C':
            final_data = show_sub_menu("🗣️ 閒聊與防禦 (Chatter/Others)", CHATTER_ROUTES, seq_iter, args.count)
        elif args.mode == 'D':
            count = args.count if args.count else 100
            final_data = MultiTurnBuilder.generate_nuanced_data(count)
        elif args.mode == 'E':
            count = args.count if args.count else 100
            final_data = SlotFillingBuilder.generate_data(count)
        elif args.mode == 'F':
            count = args.count if args.count else 100
            final_data = NLGBuilder.generate_data(count)
            
        if final_data is not None:
            save_data(final_data, final_output_path)
        return

    # =========================================================
    # 終端機互動模式
    # =========================================================
    while True:
        print("\n" + "="*55)
        print(" 🍔 [意圖分區] 終極 OOP 模組化引擎 v22.0 (全任務大一統)")
        print("="*55)
        print(" [A] 🍽️ 推薦意圖 (Task 1: Recommend)")
        print(" [B] 🔍 查詢意圖 (Task 1: Query)")
        print(" [C] 🗣️ 閒聊與防禦 (Task 1: Chatter/Others)")
        print(" [D] 🔄 產生多輪對話 (20 種地獄細膩情境) 👑")
        print(" [E] ❓ 槽位補問 (Task 2: Slot Filling) 🆕")
        print(" [F] 💬 前端卡片推坑 (Task 3: NLG) 🆕")
        print(" [Q] 💾 離開")
        print("-" * 55)
        
        try:
            main_choice = consume_input("👉 請選擇任務 (A/B/C/D/E/F/Q): ").upper()
        except EOFError: 
            break
            
        final_data = None
        if main_choice == 'A':
            final_data = show_sub_menu("🍽️ 推薦 (Recommend)", RECOMMEND_ROUTES)
        elif main_choice == 'B':
            final_data = show_sub_menu("🔍 查詢 (Query)", QUERY_ROUTES)
        elif main_choice == 'C':
            final_data = show_sub_menu("🗣️ 閒聊與防禦 (Chatter/Others)", CHATTER_ROUTES)
        elif main_choice == 'D':
            num_str = consume_input("\n👉 請問要產生幾組多輪劇本？(預設 100): ")
            generate_count = int(num_str) if num_str.isdigit() and int(num_str) > 0 else 100
            print(f"\n🚀 正在極速合成 {generate_count} 筆地獄級多輪資料...")
            final_data = MultiTurnBuilder.generate_nuanced_data(generate_count)
            
        # 🎯 新增：Task 2 槽位補問的觸發邏輯
        elif main_choice == 'E':
            num_str = consume_input("\n👉 請問要產生幾筆 Task 2 (槽位補問) 資料？(預設 100): ")
            generate_count = int(num_str) if num_str.isdigit() and int(num_str) > 0 else 100
            final_data = SlotFillingBuilder.generate_data(generate_count)
            
        # 🎯 新增：Task 3 自然生成 (前端卡片) 的觸發邏輯
        elif main_choice == 'F':
            num_str = consume_input("\n👉 請問要產生幾筆 Task 3 (卡片推坑) 資料？(預設 100): ")
            generate_count = int(num_str) if num_str.isdigit() and int(num_str) > 0 else 100
            final_data = NLGBuilder.generate_data(generate_count)
            
        elif main_choice == 'Q':
            print("\n👋 引擎已關閉。祝專題順利！")
            break
        else:
            print("\n❌ 無效的選擇。")
            
        if final_data is not None:
            save_data(final_data, final_output_path)

if __name__ == "__main__":
    main()