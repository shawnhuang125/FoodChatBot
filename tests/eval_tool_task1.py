import streamlit as st
import json
import os
import plotly.express as px
from copy import deepcopy
import sys
import asyncio
import time
from datetime import datetime
from json_repair import loads as repair_loads

# ==========================================
# 解決跨目錄導入問題 (將專案根目錄加入路徑)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

APP_DIR = os.path.join(PROJECT_ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from app.infer import load_all_models, infer
from app.system_prompt import TASK_PROMPTS
from app.message_builder import MessageBuilder
from app.memory_manager import UserMemory

# ==========================================
# ⚙️ 系統與路徑設定
# ==========================================
st.set_page_config(page_title="JOY-EVAL 批量測試與審核", layout="wide", page_icon="⚖️")

# 修改輸出目錄：儲存在目前檔案同目錄(tests)下的 eval_results 裡
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "eval_results"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==========================================
# 🔌 正式串接模型推論
# ==========================================
@st.cache_resource
def init_model():
    """ 確保模型只會被初始化一次並保留在記憶體中 """
    load_all_models()
    return True

def get_model_prediction(messages: list, mode="task1") -> dict:
    """ 呼叫正式推理方法，並回傳解析後的 Python Dictionary """
    init_model()  # 確保模型已載入

    async def run_infer():
        raw_json_output = ""
        async for chunk in infer(messages, mode=mode):
            raw_json_output += chunk
        return raw_json_output

    raw_output = asyncio.run(run_infer())
    
    # 強化 JSON 安全解析：清洗 Markdown 標籤與首尾空白
    clean_json = raw_output.replace("```json", "").replace("```", "").strip()
    start_idx = clean_json.find('{')
    end_idx = clean_json.rfind('}')
    if start_idx != -1 and end_idx != -1:
        clean_json = clean_json[start_idx:end_idx+1]
    
    try:
        res = repair_loads(clean_json)
        if not isinstance(res, dict):
            res = {}
        return res
    except Exception as e:
        return {"error": "模型輸出非標準 JSON", "raw_output": raw_output}

# ==========================================
# 💾 資料儲存與 Session 初始化
# ==========================================
def init_state():
    if "mode" not in st.session_state:
        st.session_state.mode = None # "test" or "review_setup"
    if "review_queue" not in st.session_state:
        st.session_state.review_queue = []
    if "stats" not in st.session_state:
        st.session_state.stats = {"total": 0, "pass": 0, "barely": 0, "fail": 0}
    if "current_index" not in st.session_state:
        st.session_state.current_index = 0
    if "test_sentences_text" not in st.session_state:
        st.session_state.test_sentences_text = ""

init_state()

def save_all_to_json(filepath, data_list):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data_list, f, ensure_ascii=False, indent=2)

# ==========================================
# 🎨 UI 輔助元件：鐵律檢查與渲染
# ==========================================
def llm_semantic_judge(sentence, context_time, pred_json):
    """ 🧠 第三層驗證：利用本地 Qwen 基礎模型進行語意與時間正確性驗證 """
    
    user_prompt = f"""你是一個極度嚴苛、具備完美主義的後端系統語意稽核專家。
    請將【使用者輸入】與解析出來的【解析結果 JSON】進行逐字、逐欄位的深度邏輯比對，找出任何潛在的語意稀釋、邏輯錯誤或格式瑕疵。

    【輸入資訊】
    - 基準當下時間 (Context Time): {context_time}
    - 使用者輸入: "{sentence}"
    - 解析結果 JSON: 
    {json.dumps(pred_json, ensure_ascii=False, indent=2)}

    【🧱 專家級深度審核鐵律 —— 只要違反任何一項，必須判定為 "不行"】

    1. 實體抓取與欄位歸屬 (Entity & Field Alignment)
       - 【預期行為】：必須「完全忠於」使用者輸入的字面意思，絕不能過度推論或腦補。使用者提到的需求必須 100% 提取，且「只能」使用以下標準欄位：address, food_type, rating, time, service_tags, flavor, cuisine, restaurant_type, restaurant_name。
       - 【特定轉換規則】：當使用者說「我附近」、「目前位置」、「周邊」等隱含當前位置的詞彙時，`address` 的 `value` 必須被轉換為 `["MY_LOCATION"]` 或是 `["使用者當前位置"]`，絕對不能直接照抄 `["目前位置"]` 或是 `["附近"]`。
       - 【致命錯誤樣態】：
         * 漏抓：漏抓關鍵字（例如說了「要素食」，但 conditions 裡完全沒有對應標籤）。
         * 錯置：分類錯誤（例如把「火鍋」這個食物種類放進 `address` 欄位）。
         * 憑空幻想或發明未定義的欄位（例如發明了 `temperature`, `price`, `atmosphere` 等欄位）。
         * 條件腦補與無中生有：這是最嚴重的錯誤！例如使用者只說了「目前位置周邊」，JSON 卻自作主張加了「中菜/西菜」的 cuisine 條件，或沒提評分卻加了 rating 條件。只要 JSON 裡的條件在使用者語意中「完全沒提過」，立刻判定為「不行」。

    2. 巢狀與單一邏輯運算子 (Logic Operator & Tree Structure)
       - 【預期行為】：
         * 結構節點的運算子 `op` 只能是 "AND", "OR", "NO_OP" 三種，絕對不能發明如 "WITHIN" 或 "TIME_INTERVAL" 等。
         * 當 conditions 陣列中「只有一個單一過濾條件」時，最外層的 `op` 必須絕對是 "NO_OP"。
         * 當語意為「或/其中一個選一個」時，必須使用 "OR"；語意為「而且/並/且」時，必須使用 "AND"。
       - 【致命錯誤樣態】：
         * 發明未定義的 `op`（例如 `WITHIN`, `TIME_INTERVAL` 等完全不是系統支援的運算子）。
         * 只有一個火鍋條件，`op` 卻給了 "AND" 或 "OR"（過度包裝）。
         * 「火鍋或燒肉」被拆成兩個條件並用 "AND" 連接。
         * 複雜嵌套（如：地點 AND (火鍋 OR 燒肉)）的層級順序顛倒。

    3. 條件冗餘與重複污染 (Condition Redundancy)
       - 【預期行為】：每一個獨立的語意條件在樹狀結構中應該「只出現一次」。
       - 【致命錯誤樣態】：
         * 同一個條件重複出現。例如 conditions 裡面出現了兩個一模一樣的時間過濾條件（不論權重 weight 是否相同，只要重複就是結構受損，判為 "不行"）。

    4. 時間與區間運算子精準度 (Time & Operator Match)
       - 【預期行為】：必須以基準時間「{context_time}」為起點，將使用者的口語時間精確推算成「絕對時間 (YYYY-MM-DD HH:MM:SS)」。
         * 時間的 `value` 絕對不允許照抄使用者口語（如 `["明天下午"]`、`["一小時後"]`），必須是具體推算出來的日期時間字串。
         * 若使用者給出明確的時間範圍（例如：17:00 到 19:00、開到凌晨兩點、半小時後到一小時後），`cmp` 必須為 "between"，且 `value` 必須包含推算後的 [起始絕對時間, 結束絕對時間] 兩個元素。
       - 【致命錯誤樣態】：
         * `time` 欄位的值沒有轉換為時間戳記，直接填寫了中文字面（如 `["晚上"]`）。
         * 明明是時間區間，`cmp` 卻偷懶用 "=" 或 "open_at"。
         * 推算日期錯誤（例如明天下午推算成今天的日期）。

    5. 🚨 追問狀態強制連動連鎖 (The Unresolved Iron Rule)
       - 【預期行為】：當使用者講出「這家」、「那間」、「剛剛那間」等模糊代名詞時，`field` 必須為 "restaurant_name"，且該條件內部必須包含 `"resolved": false`。此時，最外層的 `"follow_up"` 必須強制為 true。
       - 【致命錯誤樣態】：
         * 發現 `"resolved": false`，但最外層的 `"follow_up"` 卻是 false 或 None。
         * 直接忽略代名詞，完全沒把它當成一個條件提取出來。

    6. 嚴格資料型態檢查 (Data Type Validation)
       - 【預期行為】：所有條件的 `value` 欄位必須是「陣列/列表 (Array/List)」，例如 `["火鍋"]`。
       - 【致命錯誤樣態】：
         * `value` 被寫成了純字串（例如 `"火鍋"`），這會導致後端系統解析崩潰。

    7. 隱含距離與排序邏輯鐵律 (Implicit Distance & Sorting Rule)
       - 【致命錯誤樣態】：若使用者說『附近』且未指定具體距離，JSON 的 conditions 內絕對不准出現 distance 欄位，且 sort_conditions 內必須『強迫出現』{{"field": "distance", "method": "ASC"}}。若未出現，一律一票否決判為『不行』！

    【📊 裁決評分標準】
    - "可以": 邏輯樹完美，無任何冗餘，運算子完全精確，格式 100% 毫無瑕疵。
    - "免強": 核心語意都抓對，搜尋邏輯也通，但存在非關鍵小瑕疵（例如 weight 權重分配不夠漂亮，或 sort_conditions 的排序前後順序微調，但不嚴重影響最終搜尋結果）。
    - "不行": 違反上述 6 大鐵律中任何一條細項、JSON 格式毀損、漏字、邏輯運算子錯誤、條件重複出現。

    【⚠️ 輸出格式要求 —— 違反格式視同系統崩潰】
    1. 你必須只輸出純 JSON 格式，絕對不准包含 ```json 這樣的 Markdown 標記，也不准有任何多餘的開場白或結尾問候。
    2. 請嚴格依照以下欄位輸出：
    {{
      "thought": "請強制輸出以下硬性比對清單的檢查結果：1. 檢查 address value 是否精準轉換為 '使用者當前位置'？ 2. 檢查是否有沒提過卻出現在 conditions 裡的幻覺值（例如 rating = MAX）？ 3. 檢查 sort_conditions 是否精準命中所有隱含排序？",
      "decision": "可以" | "免強" | "不行",
      "error_location": "若有錯誤，請寫出具體的欄位路徑（例如: logic_tree.conditions[2].op），若無錯誤則填 '無'",
      "reason": "指出違反了哪一條鐵律或具體瑕疵原因，字數請精簡在 50 字以內"
    }}
    """
    
    messages = [
        {"role": "system", "content": "你是一個國家級的語意解析評分專家，負責對 AI 解析出來的 JSON 進行最終品質控管。請嚴格遵守只回傳 JSON 格式，絕對不允許包含任何 Markdown 標籤或額外文字。"},
        {"role": "user", "content": user_prompt}
    ]

    async def run_infer():
        raw_json_output = ""
        async for chunk in infer(messages, mode="base"):
            raw_json_output += chunk
        return raw_json_output

    try:
        raw_output = asyncio.run(run_infer())
        clean_json = raw_output.replace("```json", "").replace("```", "").strip()
        
        # 增強過濾：確保只解析 { } 之間的內容
        start_idx = clean_json.find('{')
        end_idx = clean_json.rfind('}')
        if start_idx != -1 and end_idx != -1:
            clean_json = clean_json[start_idx:end_idx+1]
            
        result = repair_loads(clean_json)
        if not isinstance(result, dict):
            result = {}
        decision = result.get("decision", "不行")
        if decision not in ["可以", "免強", "不行"]:
            decision = "不行"
            
        error_location = result.get("error_location", "無")
        reason = result.get("reason", "無")
        remark_text = f"[🧠 語意驗證] {reason}"
        if error_location and error_location != "無":
            remark_text += f" | 📍錯誤位置: {error_location}"
            
        # 🎯 Python 雙重防呆校驗
        if decision == "可以":
            json_str = json.dumps(pred_json, ensure_ascii=False)
            has_literal_location = "現在位置" in json_str or "目前位置" in json_str
            has_hallucinated_max = "MAX" in json_str
            
            if has_literal_location or has_hallucinated_max:
                decision = "不行"
                remark_text += " | 🛑 [Python 硬體防呆] 觸發字面轉換與過濾幻覺違規"
            
        return decision, remark_text
    except Exception as e:
        return "免強", f"[🧠 語意驗證] 模型推論或解析失敗，降級為免強: {str(e)} | 原始輸出: {raw_output}"

def _check_unresolved(node):
    # 🎯 防護網 1：如果 node 根本不是字典 (比如模型幻覺產出了純字串)，直接安全跳過
    if not node or not isinstance(node, dict): 
        return False
    if "op" in node and "conditions" in node:
        conditions = node.get("conditions", [])
        if isinstance(conditions, list):
            return any(_check_unresolved(c) for c in conditions)
        return False
    return node.get("resolved") is False

def auto_judge(json_data):
    """ 🤖 自動驗證邏輯：判定模型輸出是否合規 """
    if "error" in json_data:
        return "不行", "JSON 解析失敗"
        
    # 1. 嚴格檢查 main_intent
    valid_intents = {"recommend", "query", "greet", "thanks", "end", "fetch_more", "unknown"}
    main_intent = json_data.get("main_intent")
    if not main_intent:
        return "不行", "缺少 main_intent 欄位"
    if main_intent not in valid_intents:
        return "不行", f"未知的 main_intent: {main_intent}"
        
    # 2. 檢查 page 與 sort_conditions 結構
    if "page" in json_data and json_data["page"] is not None:
        if not isinstance(json_data["page"], int):
            return "不行", "page 必須是整數"
            
    if "sort_conditions" in json_data:
        sc = json_data["sort_conditions"]
        if not isinstance(sc, list):
            return "不行", "sort_conditions 必須是陣列"
        for cond in sc:
            if not isinstance(cond, dict) or "field" not in cond or "method" not in cond:
                return "不行", "sort_conditions 內容格式錯誤 (需包含 field 與 method)"

    # 3. 嚴重鐵律檢查 (Unresolved -> Follow up)
    logic_tree = json_data.get("logic_tree")
    follow_up = json_data.get("follow_up")
    has_unresolved = _check_unresolved(logic_tree)
    if has_unresolved and not follow_up:
        return "不行", "嚴重違規：含有未解節點但未觸發 follow_up"
        
    def check_node(node):
        if not node or not isinstance(node, dict): return True, ""
        
        if "op" in node and "conditions" in node:
            if node["op"] not in ["AND", "OR", "NO_OP"]:
                return False, f"未知的邏輯運算子 (op): {node['op']}"
                
            conditions = node.get("conditions", [])
            # 🎯 防護網 2：如果 conditions 不是陣列，優雅判斷為格式錯誤而不崩潰
            if not isinstance(conditions, list):
                return False, "conditions 必須是陣列 (Array)"
            for c in conditions:
                ok, msg = check_node(c)
                if not ok: return False, msg
            return True, ""
            
        elif "field" in node:
            # 嚴格限制欄位名稱，拒絕模型發明未定義的欄位 (幻覺)
            valid_fields = {"address", "food_type", "rating", "time", "service_tags", "flavor", "cuisine", "restaurant_type", "restaurant_name"}
            if node["field"] not in valid_fields:
                return False, f"發明未知欄位 (幻覺): {node['field']}"
                
            if "value" not in node or not isinstance(node["value"], list):
                return False, f"欄位 {node['field']} 的 value 必須是陣列 (Array)"
            if "cmp" not in node:
                return False, f"欄位 {node['field']} 缺少 cmp 運算子"
            if "constraint_level" not in node or node["constraint_level"] not in ["MUST", "SHOULD"]:
                return False, f"欄位 {node['field']} 的 constraint_level 錯誤 ({node.get('constraint_level')})"
            if "weight" in node:
                if not isinstance(node["weight"], (int, float)) or not (0.0 <= node["weight"] <= 1.0):
                    return False, f"欄位 {node['field']} 的 weight 必須介於 0.0 到 1.0 之間"
                
        return True, ""

    if logic_tree:
        ok, msg = check_node(logic_tree)
        if not ok:
            return "不行", f"嚴重格式/欄位瑕疵: {msg}" # 語法未遵守專案規範
            
    return "可以", "自動驗證通過 (格式與鐵律合規)"

def render_iron_law_check(json_data):
    """ 針對 resolved: false 必定觸發 follow_up: true 的鐵律進行高亮提示 """
    if not isinstance(json_data, dict): return
    
    logic_tree = json_data.get("logic_tree")
    follow_up = json_data.get("follow_up")
    has_unresolved = _check_unresolved(logic_tree)
    
    st.markdown("##### 🚨 鐵律檢查 (Iron Law)")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("含 unresolved 節點", "是" if has_unresolved else "否")
    with col2:
        st.metric("Follow Up 狀態", str(follow_up))
    with col3:
        if has_unresolved and not follow_up:
            st.error("❌ 嚴重違規：有未解節點但未觸發 follow_up!")
        elif has_unresolved and follow_up:
            st.success("✅ 完美合規：未解節點正確觸發 follow_up!")
        else:
            st.info("ℹ️ 無未解節點。")

# ==========================================
# 🎨 側邊欄與首頁選擇
# ==========================================
with st.sidebar:
    st.header("🎛️ 模式切換")
    if st.button("🚀 批次測試模式", use_container_width=True):
        st.session_state.mode = "test"
        st.rerun()
    if st.button("🕵️ 人工審核模式", use_container_width=True):
        st.session_state.mode = "review_setup"
        st.rerun()
    if st.button("📊 檢視審核報告", use_container_width=True):
        st.session_state.mode = "view_report"
        st.rerun()

if st.session_state.mode is None:
    st.title("⚖️ JOY-EVAL 批量測試與審核工具")
    st.write("請從左側邊欄選擇要執行的模式。")
    st.write("- **批次測試模式**: 上傳包含多個句子的 TXT 或 JSON 檔案，自動生成 Task 1 推論結果並儲存。")
    st.write("- **人工審核模式**: 讀取先前的測試結果，逐筆審核並加上備註，將分為「可以」、「免強」、「不行」三個等級。")
    st.write("- **檢視審核報告**: 隨時讀取已審核的檔案，查看品質得分率、數據圓餅圖，並快速瀏覽有問題的預測結果。")

# ==========================================
# 🚀 模式 1：批次測試模式 (Batch Test)
# ==========================================
elif st.session_state.mode == "test":
    st.title("🚀 批次測試模式")
    st.write("請手動輸入或上傳包含測試句子的檔案。")
    st.write("支援格式：\n- **手動輸入 / TXT檔案**: 每行一個句子\n- **JSON檔案**: 包含字串的陣列 (例如: `[\"句子1\", \"句子2\"]`)")
    
    tab1, tab2 = st.tabs(["✍️ 編輯區 (輸入與修改)", "📂 讀取測試集檔案"])
    
    with tab2:
        uploaded_file = st.file_uploader("📂 上傳 .txt 或 .json", type=["txt", "json"])
        if uploaded_file is not None:
            if st.button("讀取並覆蓋至編輯區"):
                try:
                    if uploaded_file.name.endswith(".json"):
                        file_sentences = json.load(uploaded_file)
                        if isinstance(file_sentences, list):
                            st.session_state.test_sentences_text = "\n".join(file_sentences)
                            st.success("讀取成功！請切換至「✍️ 編輯區」查看與修改。")
                        else:
                            st.error("JSON 檔案必須是一個包含句子的陣列。")
                    else:
                        text = uploaded_file.getvalue().decode("utf-8")
                        st.session_state.test_sentences_text = text
                        st.success("讀取成功！請切換至「✍️ 編輯區」查看與修改。")
                except Exception as e:
                    st.error(f"檔案解析失敗: {e}")

    with tab1:
        manual_input = st.text_area(
            "貼上或輸入測試句子 (每行一句)", 
            height=300, 
            placeholder="我想找火鍋\n幫我查永康區的飲料店",
            key="test_sentences_text"
        )
        
        sentences = [line.strip() for line in manual_input.splitlines() if line.strip()]
                
    if sentences:
        st.success(f"目前共載入 {len(sentences)} 筆測試句子！")
        
        st.markdown("### 儲存與推論")
        col1, col2 = st.columns(2)
        
        with col1:
            with st.container(border=True):
                st.write("📥 儲存測試集")
                dataset_filename = st.text_input("儲存測試集的檔名", value="my_test_cases.json")
                if st.button("💾 將目前的句子存檔", use_container_width=True):
                    dataset_path = os.path.join(OUTPUT_DIR, dataset_filename)
                    try:
                        if dataset_filename.endswith(".json"):
                            save_all_to_json(dataset_path, sentences)
                        else:
                            with open(dataset_path, "w", encoding="utf-8") as f:
                                f.write("\n".join(sentences))
                        st.success(f"測試集已儲存至：`{dataset_path}`")
                    except Exception as e:
                        st.error(f"儲存失敗: {e}")
        
        with col2:
            with st.container(border=True):
                import app.infer as infer_module
                st.write("🚀 執行推論")
                
                # 偵測目前所有的 Checkpoints
                base_model_dir = os.getenv("MODELS_BASE_DIR", os.path.join(PROJECT_ROOT, "models", "qwen2.5-7b"))
                # 直接指定 MODELS_BASE_DIR 下的 task1 目錄
                task1_full_dir = os.path.join(base_model_dir, "task1")
                
                checkpoints = []
                if os.path.exists(task1_full_dir):
                    for d in os.listdir(task1_full_dir):
                        if d.startswith("checkpoint-") or d == "final_lora_adapter":
                            checkpoints.append(os.path.join(task1_full_dir, d))
                # 將 checkpoint 依照 step 排序
                checkpoints.sort(key=lambda x: int(os.path.basename(x).split('-')[1]) if "checkpoint-" in x else 999999)
                
                do_sweep = st.checkbox(f"🔄 Sweep Mode (自動連續測試目錄下所有 {len(checkpoints)} 個 Checkpoint)", value=True)
                do_auto_judge = st.checkbox("🤖 啟用 Auto-Judge (自動判斷格式合規性並標記)", value=True)
                do_semantic_judge = st.checkbox("🧠 啟用 LLM 語意驗證 (使用本地 Qwen 基礎模型)", value=True)
                do_early_stop = st.checkbox("🛑 啟用提早放棄機制 (若前 5 筆推論錯誤率 ≥ 50%，自動跳過該模型)", value=True)
                output_prefix = st.text_input("儲存推論結果的檔名前綴", value="batch_results")
                
                if st.button("開始批次推論", use_container_width=True, type="primary"):
                    target_checkpoints = checkpoints if do_sweep else [os.path.join(task1_full_dir, os.path.basename(os.getenv("TASK1_ADAPTER_DIR", "final_lora_adapter")))]
                    
                    ckpt_progress = st.progress(0)
                    status_text = st.empty()
                    summary_report = []
                    
                    sys_prompt = TASK_PROMPTS.get("task1", "你是一個語意解析引擎...")
                    builder = MessageBuilder()
                    
                    for c_idx, ckpt_path in enumerate(target_checkpoints):
                        ckpt_name = os.path.basename(ckpt_path)
                        adapter_name = f"task1_{ckpt_name}"
                        
                        status_text.text(f"📥 正在載入模型權重: {ckpt_name} ...")
                        init_model()  # 確保底座模型已經載入，否則 model 為 None
                        if adapter_name not in infer_module.model.peft_config:
                            infer_module.model.load_adapter(ckpt_path, adapter_name=adapter_name)
                        
                        pass_cnt, barely_cnt, fail_cnt = 0, 0, 0
                        aborted = False
                        
                        results = []
                        for i, sentence in enumerate(sentences):
                            status_text.text(f"[{ckpt_name}] 正在推論第 {i+1}/{len(sentences)} 筆: {sentence}")
                            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            mem = UserMemory(user_id=f"eval_user_{i}")
                            turn = mem.new_turn()
                            turn.user_input = sentence
                            
                            messages, _ = builder.build_messages(memory=mem, mode="task1", system_prompt=sys_prompt, context_time=current_time)
                            pred_json = get_model_prediction(messages, mode=adapter_name)
                            
                            result_entry = {
                                "id": i + 1, "sentence": sentence,
                                "context_time": current_time, "model_output": pred_json
                            }
                            
                            if do_auto_judge:
                                decision, remark = auto_judge(pred_json)
                                
                                # 結構合規後，才執行語意驗證 (節省 API 呼叫次數)
                                if decision == "可以" and do_semantic_judge:
                                    status_text.text(f"[{ckpt_name}] 正在進行 🧠 LLM 語意驗證: 第 {i+1} 筆 ...")
                                    sem_dec, sem_rem = llm_semantic_judge(sentence, current_time, pred_json)
                                    decision = sem_dec
                                    remark = sem_rem
                                
                                result_entry["review_result"] = decision
                                result_entry["review_remark"] = remark
                                
                                if decision == "可以": pass_cnt += 1
                                elif decision == "免強": barely_cnt += 1
                                elif decision == "不行": fail_cnt += 1
                                
                            results.append(result_entry)
                            ckpt_progress.progress((c_idx + (i + 1) / len(sentences)) / len(target_checkpoints))
                            
                            # 🎯 [即時存檔] 每推論完一句話就立刻寫入檔案，方便你隨時在外部抽查該 Checkpoint 的狀況
                            save_path = os.path.join(OUTPUT_DIR, f"{output_prefix}_{ckpt_name}.json")
                            save_all_to_json(save_path, results)
                            
                            # --- 提早放棄機制 (Early Stopping) ---
                            if do_sweep and do_early_stop and do_auto_judge and (i + 1) >= 5:
                                fail_rate = fail_cnt / (i + 1)
                                if fail_rate >= 0.5:
                                    status_text.text(f"🛑 [{ckpt_name}] 錯誤率達 {fail_rate*100:.1f}%，觸發提早放棄！")
                                    aborted = True
                                    break
                        
                        total_eval = pass_cnt + barely_cnt + fail_cnt
                        score = 0
                        if total_eval > 0:
                            score = (pass_cnt * 1.0 + barely_cnt * 0.5) / total_eval * 100
                            
                        summary_report.append({
                            "Checkpoint": ckpt_name,
                            "測試數": total_eval,
                            "可以": pass_cnt,
                            "免強": barely_cnt,
                            "不行": fail_cnt,
                            "品質得分": round(score, 2),
                            "狀態": "已放棄 🛑" if aborted else "完成 ✅"
                        })
                        
                    status_text.text("✅ 所有推論與驗證完成！")
                    if do_sweep:
                        st.success(f"全量測試結束！所有 Checkpoint 的結果已分別儲存於目錄中。")
                        st.subheader("📊 Sweep Checkpoint 總結比較")
                        st.dataframe(summary_report, use_container_width=True)
                        
                        if summary_report:
                            fig = px.bar(summary_report, x="Checkpoint", y="品質得分", color="狀態", title="各版本品質得分比較", text_auto=True)
                            st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.success(f"測試結果已儲存至：`{save_path}`")

# ==========================================
# 🕵️ 模式 2：人工審核模式 (Review Setup & Process)
# ==========================================
elif st.session_state.mode == "review_setup":
    st.title("🕵️ 人工審核模式")
    
    # 掃描 output dir 的 json 檔案
    json_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".json")]
    
    if not json_files:
        st.warning(f"在 {OUTPUT_DIR} 中找不到任何 JSON 檔案，請先進行批次測試。")
    else:
        selected_file = st.selectbox("請選擇要審核的檔案:", json_files)
        
        if st.button("開始審核", type="primary"):
            file_path = os.path.join(OUTPUT_DIR, selected_file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 過濾掉已經審核過的 (如果有 review_result 欄位)
                st.session_state.review_queue = [item for item in data if "review_result" not in item]
                st.session_state.original_file = file_path
                st.session_state.all_data = data # 保留全部以便後續更新覆寫
                
                st.session_state.stats = {"total": len(st.session_state.review_queue), "pass": 0, "barely": 0, "fail": 0}
                st.session_state.current_index = 0
                
                if not st.session_state.review_queue:
                    st.info("此檔案內的所有資料皆已審核完畢！")
                else:
                    st.session_state.mode = "review_process"
                    st.rerun()
            except Exception as e:
                st.error(f"讀取檔案失敗: {e}")

elif st.session_state.mode == "review_process":
    queue_len = len(st.session_state.review_queue)
    total = st.session_state.stats["total"]
    current_idx = st.session_state.current_index
    
    if current_idx >= queue_len:
        st.session_state.mode = "report"
        st.rerun()
        st.stop()
        
    current_case = st.session_state.review_queue[current_idx]
    
    st.title(f"🕵️ 審核中 ({current_idx + 1}/{total})")
    st.progress((current_idx) / total)
    
    # --- 展示區 ---
    st.markdown(f"### 💬 使用者輸入\n> **{current_case.get('sentence', current_case.get('user', '未知的輸入'))}**")
    
    st.subheader("🤖 模型輸出")
    output_data = current_case.get("model_output", current_case.get("pred", current_case))
    
    if "error" in output_data:
        st.error(f"⚠️ {output_data['error']}")
        st.text(output_data.get("raw_output", ""))
    else:
        st.json(output_data)
        render_iron_law_check(output_data)
        
    st.divider()
    
    # --- 操作區 ---
    st.markdown("### 📝 審核決策")
    remark_key = f"remark_{current_idx}"
    
    # 使用 st.form 來避免 Enter 提早送出刷新，或者就直接放 text_input
    remark = st.text_input("備註 (可選填):", key=remark_key)
    
    col1, col2, col3 = st.columns(3)
    
    def process_decision(decision):
        current_case["review_result"] = decision
        current_case["review_remark"] = st.session_state[remark_key]
        
        if decision == "可以":
            st.session_state.stats["pass"] += 1
        elif decision == "免強":
            st.session_state.stats["barely"] += 1
        else:
            st.session_state.stats["fail"] += 1
            
        for item in st.session_state.all_data:
            if item.get("id") == current_case.get("id"):
                item["review_result"] = current_case["review_result"]
                item["review_remark"] = current_case["review_remark"]
                break
        
        save_all_to_json(st.session_state.original_file, st.session_state.all_data)
        st.session_state.current_index += 1
    
    with col1:
        if st.button("🟢 可以 (Accept)", use_container_width=True, type="primary"):
            process_decision("可以")
            st.rerun()
    with col2:
        if st.button("🟡 免強 (Barely)", use_container_width=True):
            process_decision("免強")
            st.rerun()
    with col3:
        if st.button("🔴 不行 (Fail)", use_container_width=True):
            process_decision("不行")
            st.rerun()
            

# ==========================================
# 📊 模式 3：報告與統計 (Report)
# ==========================================
elif st.session_state.mode == "report":
    st.title("🎉 評估任務完成！")
    st.balloons()
    
    stats = st.session_state.stats
    
    if stats["total"] > 0:
        score = ((stats["pass"] * 1.0) + (stats["barely"] * 0.5)) / stats["total"] * 100
        st.metric("🎯 最終品質得分率", f"{score:.1f} / 100")

    col1, col2, col3 = st.columns(3)
    col1.metric("🟢 可以", stats["pass"])
    col2.metric("🟡 免強", stats["barely"])
    col3.metric("🔴 不行", stats["fail"])
    
    st.divider()
    
    if stats["total"] > 0:
        fig = px.pie(
            values=[stats["pass"], stats["barely"], stats["fail"]], 
            names=['🟢 可以', '🟡 免強', '🔴 不行'],
            title='審核結果分佈',
            color_discrete_map={'🟢 可以':'#2E8B57', '🟡 免強':'#F4A460', '🔴 不行':'#CD5C5C'}
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)
        
    st.success(f"所有審核結果已更新並儲存至：`{st.session_state.original_file}`")
    
    if st.button("🔄 回到首頁"):
        st.session_state.mode = None
        st.rerun()

# ==========================================
# 📊 模式 4：檢視審核報告 (View Report)
# ==========================================
elif st.session_state.mode == "view_report":
    st.title("📊 檢視審核報告")
    
    json_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".json")]
    
    if not json_files:
        st.warning(f"在 {OUTPUT_DIR} 中找不到任何 JSON 檔案。")
    else:
        selected_files = st.multiselect("請選擇要查看報告的檔案 (可多選以進行比較):", json_files)
        
        if st.button("載入報告", type="primary") and selected_files:
            summary_data = []
            file_reports = {}
            
            for selected_file in selected_files:
                file_path = os.path.join(OUTPUT_DIR, selected_file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                    total_reviewed = 0
                    pass_cnt, barely_cnt, fail_cnt = 0, 0, 0
                    
                    for item in data:
                        if "review_result" in item:
                            total_reviewed += 1
                            if item["review_result"] == "可以": pass_cnt += 1
                            elif item["review_result"] == "免強": barely_cnt += 1
                            elif item["review_result"] == "不行": fail_cnt += 1
                            
                    score = 0
                    if total_reviewed > 0:
                        score = (pass_cnt * 1.0 + barely_cnt * 0.5) / total_reviewed * 100
                        
                    summary_data.append({
                        "檔案名稱": selected_file,
                        "測試數": total_reviewed,
                        "可以": pass_cnt,
                        "免強": barely_cnt,
                        "不行": fail_cnt,
                        "品質得分": round(score, 2)
                    })
                    
                    file_reports[selected_file] = {
                        "data": data, "total_reviewed": total_reviewed,
                        "pass_cnt": pass_cnt, "barely_cnt": barely_cnt,
                        "fail_cnt": fail_cnt, "score": score
                    }
                except Exception as e:
                    st.error(f"讀取檔案 {selected_file} 失敗: {e}")
            
            # --- 區塊一：跨檔案比較 Leaderboard ---
            if len(selected_files) > 1 and summary_data:
                st.subheader("🏆 跨檔案品質比較 (Leaderboard)")
                st.dataframe(summary_data, use_container_width=True)
                
                fig = px.bar(summary_data, x="檔案名稱", y="品質得分", color="檔案名稱", title="各檔案品質得分比較", text_auto=True)
                st.plotly_chart(fig, use_container_width=True)
                st.divider()
            
            # --- 區塊二：單一檔案詳細報告 (使用 Tabs 切換) ---
            st.subheader("📄 詳細報告")
            tabs = st.tabs(selected_files) if len(selected_files) > 1 else [st.container()]
            
            for idx, selected_file in enumerate(selected_files):
                with tabs[idx]:
                    report = file_reports.get(selected_file)
                    if not report: continue
                    
                    st.markdown(f"#### {selected_file} (共 {len(report['data'])} 筆, 已審核 {report['total_reviewed']} 筆)")
                    
                    if report['total_reviewed'] > 0:
                        st.metric("🎯 品質得分率 (可以=100%, 免強=50%)", f"{report['score']:.1f} / 100")
                        
                        col1, col2, col3 = st.columns(3)
                        col1.metric("🟢 可以", report['pass_cnt'])
                        col2.metric("🟡 免強", report['barely_cnt'])
                        col3.metric("🔴 不行", report['fail_cnt'])
                        
                        fig_pie = px.pie(
                            values=[report['pass_cnt'], report['barely_cnt'], report['fail_cnt']], 
                            names=['🟢 可以', '🟡 免強', '🔴 不行'],
                            title=f'{selected_file} 審核結果分佈',
                            color_discrete_map={'🟢 可以':'#2E8B57', '🟡 免強':'#F4A460', '🔴 不行':'#CD5C5C'}
                        )
                        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                        st.plotly_chart(fig_pie, use_container_width=True, key=f"pie_{idx}")
                        
                        st.markdown("##### 📝 需關注的資料 (不行 / 免強)")
                        issues = [item for item in report['data'] if item.get("review_result") in ["不行", "免強"]]
                        if issues:
                            for item in issues:
                                with st.expander(f"{item.get('review_result')} | {item.get('sentence', '未知輸入')} | 備註: {item.get('review_remark', '')}"):
                                    st.json(item)
                        else:
                            st.success("太棒了！目前審核過的資料全都標記為「可以」！")
                    else:
                        st.info("此檔案目前還沒有任何審核紀錄。")