import json
import os
import inspect
from dotenv import load_dotenv
from dataset_manifest import TASK_PROMPTS

def process_dataset(input_path: str, output_path: str) -> bool:
    """ 
    將原始產生的資料集轉換為模型訓練格式。
    採用「狀態機循序掃描 (State Machine + Sequential Scanning)」策略，
    確保 100% 對齊 MessageBuilder 且無未來資訊洩漏。
    """
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 讀取失敗: {e}")
        return False

    # 🎯 預先清洗標準 System Prompt，確保絕對對齊
    CLEANED_PROMPTS = {
        1: inspect.cleandoc(TASK_PROMPTS.get("task1", "")).strip(),
        2: inspect.cleandoc(TASK_PROMPTS.get("task2", "")).strip(),
        3: inspect.cleandoc(TASK_PROMPTS.get("task3", "")).strip()
    }

    processed_data = []

    for item in data:
        raw_messages = item.get("messages", [])
        if not raw_messages: continue

        # --- 步驟 1：判定 Task 類型 ---
        mode_str = "task1"
        cleaned_instruction = ""
        for msg in raw_messages:
            if msg["role"] == "system":
                cleaned_instruction = inspect.cleandoc(msg["content"]).strip()
                if cleaned_instruction == CLEANED_PROMPTS[2]: 
                    mode_str = "task2"
                elif cleaned_instruction == CLEANED_PROMPTS[3]: 
                    mode_str = "task3"
                break

        # ==========================================
        # 步驟 2：狀態機循序掃描 (模擬真實推論時序)
        # ==========================================
        # memory_turns 負責記錄「過去」已經完成的輪次
        memory_turns = []
        
        # 暫存區：用來裝「當下這一輪」正在發生的零件
        current_user = None
        current_json = None
        
        # turn_counter 用來給歷史紀錄上 ID
        turn_counter = 1

        for msg in raw_messages:
            role = msg["role"]
            content = msg["content"]
            
            if role == "system":
                continue
                
            elif role == "user":
                # 新的一輪開始了
                current_user = content
                
            elif role == "assistant":
                # 收到 JSON 輸出
                current_json = content
                
                # 🍔 【觸發點：Task 1】
                # 在 Task 1 中，當 AI 輸出 JSON 時，這就是我們要訓練的目標！
                if mode_str == "task1":
                    target_input = current_user
                    target_output = current_json
                    
                    # 1. 構建 Dialog Context (History)
                    dialog_state = []
                    for t in memory_turns:
                        # Task 1 歷史：只存 response_output (與可能的 query_id)
                        turn_obj = {"turn_id": t["turn_id"], "response_output": t["response_output"]}
                        if t.get("query_id"): turn_obj["query_id"] = t["query_id"]
                        dialog_state.append(turn_obj)

                    combined_system = (
                        f"## System Instruction\n{cleaned_instruction}\n\n"
                        f"## Dialog Context (History)\n{json.dumps(dialog_state, ensure_ascii=False, indent=2)}"
                    )
                    
                    # 2. 構建 Messages 陣列
                    training_messages = [{"role": "system", "content": combined_system}]
                    
                    # 放入過去的對話
                    for t in memory_turns:
                        training_messages.append({"role": "user", "content": t["user_input"]})
                        training_messages.append({"role": "assistant", "content": t["json_output"]})
                    
                    # 放入當下要預測的對話
                    training_messages.append({"role": "user", "content": target_input})
                    training_messages.append({"role": "assistant", "content": target_output})
                    
                    processed_data.append({"messages": training_messages})

            elif role == "assistant 1":
                # 收到人話回覆
                current_response = content
                
                # ❓ 【觸發點：Task 2 & 3】
                # 在 Task 2/3 中，當 AI 講出人話時，這才是我們要訓練的目標！
                if mode_str in ["task2", "task3"]:
                    
                    # 1. 構建 Dialog Context (History)
                    dialog_state = []
                    for t in memory_turns:
                        if mode_str == "task2":
                            # Task 2 歷史：只存 user_input
                            dialog_state.append({"turn_id": t["turn_id"], "user_input": t["user_input"]})
                        elif mode_str == "task3":
                            # Task 3 歷史：存 user_input + response_output
                            turn_obj = {"turn_id": t["turn_id"], "user_input": t["user_input"]}
                            if t.get("response_output"): turn_obj["response_output"] = t["response_output"]
                            dialog_state.append(turn_obj)
                            
                    # 💡 關鍵：對 Task 2/3 而言，當前的 User 已經講話了，所以要放進 History！
                    if mode_str == "task2":
                        dialog_state.append({"turn_id": turn_counter, "user_input": current_user})
                    elif mode_str == "task3":
                        # Task 3 當下還沒有 response_output，所以只放 user_input
                        dialog_state.append({"turn_id": turn_counter, "user_input": current_user})

                    combined_system = (
                        f"## System Instruction\n{cleaned_instruction}\n\n"
                        f"## Dialog Context (History)\n{json.dumps(dialog_state, ensure_ascii=False, indent=2)}"
                    )
                    
                    # 2. 構建 Messages 陣列
                    training_messages = [{"role": "system", "content": combined_system}]
                    
                    if mode_str == "task2":
                        # Task 2 放入過去的對話 (JSON變User，人話變Assistant)
                        for t in memory_turns:
                            training_messages.append({"role": "user", "content": t["json_output"]})
                            training_messages.append({"role": "assistant", "content": t["response_output"]})
                        
                        # 當下要預測的對話
                        training_messages.append({"role": "user", "content": current_json})
                        training_messages.append({"role": "assistant", "content": current_response})
                    
                    elif mode_str == "task3":
                        # Task 3 完全不放過去的對話，只放當下的 JSON (datas) 與人話
                        training_messages.append({"role": "user", "content": current_json})
                        training_messages.append({"role": "assistant", "content": current_response})
                    
                    processed_data.append({"messages": training_messages})

                # --- 輪次收尾：當收到 assistant 1，代表這一整輪所有零件都齊全了 ---
                # 將這輪打包存入記憶體中，供下一輪當作歷史參考
                memory_turns.append({
                    "turn_id": turn_counter,
                    "user_input": current_user,
                    "json_output": current_json,
                    "response_output": current_response,
                    "query_id": None # 預設為 None，若後面抓到再更新
                })
                
                # 準備迎接下一輪
                current_user = None
                current_json = None
                current_response = None
                turn_counter += 1

            elif role == "query_id":
                # 抓到 query_id，直接更新給最後一筆進入 memory 的歷史紀錄
                if memory_turns:
                    memory_turns[-1]["query_id"] = content

    # --- 步驟 3：儲存 ---
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 狀態機轉換成功！產出 {len(processed_data)} 筆訓練樣本。")
        return True
    except Exception as e:
        print(f"❌ 儲存失敗: {e}")
        return False

if __name__ == "__main__":
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    INPUT_FILE = os.path.join(PROJECT_ROOT, "dataset/auto_dataset.json") 
    OUTPUT_FILE = os.path.join(PROJECT_ROOT, "dataset", "formatted_dataset.json")
    process_dataset(INPUT_FILE, OUTPUT_FILE)