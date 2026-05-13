import json

class MessageBuilder:
    """ [對話組裝模組] 根據不同的任務模式 (Task1, Task2, Task3) 組裝專屬的對話上下文，提供給大腦推論使用。 """
    def __init__(self):
        pass

    def build_dialog_state(self, memory, mode: str):
        """ 根據不同任務模式，提取並構建對應階段所需的歷史狀態(Dialog Context) """
        dialog_state = []
        for t in memory.get_all_turns():
            if mode == "task1" and t.response_output is not None:
                # 🎯 改寫這裡，如果有 query_id 就放進字典裡
                turn_obj = {
                    "turn_id": t.turn_id,
                    "response_output": t.response_output
                }
                if getattr(t, "query_id", None) is not None:
                    turn_obj["query_id"] = t.query_id
                dialog_state.append(turn_obj)
            elif mode == "task2" and t.user_input is not None:
                dialog_state.append({
                    "turn_id": t.turn_id,
                    "user_input": t.user_input
                })
            elif mode == "task3" and t.user_input is not None:
                turn_obj = {
                    "turn_id": t.turn_id,
                    "user_input": t.user_input
                }
                if t.response_output:
                    turn_obj["response_output"] = t.response_output
                dialog_state.append(turn_obj)

        return dialog_state
    
    def build_messages(self, memory, system_prompt: str = None, mode: str = None, datas=None):
        """ 生成送往模型端點前的最終標準 Message JSON Array 結構 """
        dialog_state = self.build_dialog_state(memory, mode)
        
        # 組合 System Prompt 與對話歷史 (JSON 格式)
        combined_system_content = (
            f"## System Instruction\n{system_prompt}\n\n"
            f"## Dialog Context (History)\n{json.dumps(dialog_state, ensure_ascii=False, indent=2)}"
        )
        
        messages = [
            {
                "role": "system",
                "content": combined_system_content
            }
        ]
        
        # 依照任務階段將歷史互動或檢索資料組裝進對話陣列
        if mode in ["task1", "task2"]:
            for t in memory.get_all_turns():
                if mode == "task1":
                    if t.user_input is not None:
                        messages.append({"role": "user", "content": t.user_input})
                    if t.json_output is not None:
                        messages.append({"role": "assistant", "content": t.json_output})
                elif mode == "task2":
                    if t.json_output is not None:
                        messages.append({"role": "user", "content": t.json_output})
                    if t.response_output is not None:
                        messages.append({"role": "assistant", "content": t.response_output})
        elif mode == "task3" and datas is not None:
            messages.append({
                "role": "user",
                "content": str(datas)
            })

        return messages, dialog_state