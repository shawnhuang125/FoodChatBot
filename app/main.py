import sys
import os
import asyncio
import json
import httpx
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple, Set, List, Any
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from json_repair import loads as repair_loads
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse, JSONResponse

# 載入自定義模組
from logger_config import setup_logger
from memory_manager import MemoryManager
from message_builder import MessageBuilder
from system_prompt import TASK_PROMPTS
from infer import infer, load_all_models

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ==========================================
# ⚙️ 基礎環境變數讀取
# ==========================================
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", 2))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", 3))
NEW_SEARCH_API_URL = os.getenv("NEW_SEARCH_API_URL")
PAGE_SEARCH_API_URL = os.getenv("PAGE_SEARCH_API_URL")

# ==========================================
# ⚙️ 業務參數配置區 (全域中繼資料)
# ==========================================
# 💡 針對 API 回傳的最外層 JSON 進行抓取，幫助 LLM 了解整體搜尋狀態
GLOBAL_REQUIRED_FIELDS = [
    "status",
    "data.is_fallback", 
    "data.ai_behavior_hint",
    "data.search_status"
]


# ==========================================
# 🚀 全局配置與資源管理
# ==========================================

class GlobalState:
    """管理全局共享資源，避免重複初始化"""
    client: httpx.AsyncClient = None
    active_tasks: Dict[str, asyncio.Task] = {}
    manager = MemoryManager()
    builder = MessageBuilder()
    logger = setup_logger("main")
    pid = os.getpid()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命週期管理：伺服器啟動與關閉時執行的動作"""
    print("🚀 準備開啟美食機器人傳送門...")
    load_all_models()
    GlobalState.client = httpx.AsyncClient(
        timeout=httpx.Timeout(float(os.getenv("API_TIMEOUT", 25.0))),
        limits=httpx.Limits(
            max_connections=int(os.getenv("HTTPX_MAX_CONNECTIONS", 100)), 
            max_keepalive_connections=int(os.getenv("HTTPX_MAX_KEEPALIVE", 20))
        )
    )
    yield
    await GlobalState.client.aclose()
    print("🛑 機器人傳送門已關閉。")

app = FastAPI(lifespan=lifespan)
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
request_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)


# ==========================================
# 🛠️ 輔助工具函數：資料清洗模組 (路徑化深搜支援)
# ==========================================

def get_value_by_path(data: dict, path: str) -> Any:
    """
    [尋路工具] 根據點路徑 (如 'data.is_fallback') 從巢狀 dict 中安全取值。
    """
    keys = path.split('.')
    val = data
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None # 如果中斷或路徑不存在，安全回傳 None
    return val

def get_required_fields(semantic_dict: dict) -> Set[str]:
    """
    [策略層] 決定需要從「餐廳資料」中撈取哪些欄位。
    """
    # 💡 系統常數：把所有「絕對不能漏」的餐廳欄位直接寫死在這裡
    needed_keys = {
        "restaurant_name", 
        "review_summary"
    }
        
    # 處理 LLM 額外判斷出的 info_needed
    if isinstance(semantic_dict.get("info_needed"), list):
        needed_keys.update(semantic_dict["info_needed"])
        
    # 處理排序依據
    if isinstance(semantic_dict.get("sort_conditions"), list):
        for cond in semantic_dict["sort_conditions"]:
            if "field" in cond:
                needed_keys.add(cond["field"])
                
    # 遞迴解析搜尋條件中的隱藏欄位
    def extract_keys_from_logic(node):
        if not node or not isinstance(node, dict): return
        if "op" in node and "conditions" in node:
            for cond in node.get("conditions", []):
                extract_keys_from_logic(cond)
        else:
            if "field" in node:
                needed_keys.add(node["field"])
                    
    extract_keys_from_logic(semantic_dict.get("logic_tree", {}))
    return needed_keys


# ==========================================
# 📡 主要 API 端點
# ==========================================

@app.post("/text_bot_input")
async def chat(request: Request):
    """聊天核心 Pipeline"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = data.get("sid")
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing sid")

    GlobalState.logger.debug(f"[PID:{GlobalState.pid}] [SID:{user_id}] 收到 Request: {json.dumps(data, ensure_ascii=False)}")

    try:
        request_queue.put_nowait(user_id)
    except asyncio.QueueFull:
        GlobalState.logger.warning(f"[PID:{GlobalState.pid}] [SID:{user_id}] 佇列已滿")
        raise HTTPException(status_code=503, detail="伺服器忙碌中")

    async def generate():
        current_task = asyncio.current_task()
        GlobalState.active_tasks[user_id] = current_task
        
        user_mem = None
        turn = None
        response_text = ""
        queue_cleared = False

        try:
            async with semaphore:
                if not request_queue.empty():
                    await request_queue.get()
                    request_queue.task_done()
                    queue_cleared = True

                loop = asyncio.get_running_loop()
                user_mem = await loop.run_in_executor(None, GlobalState.manager.get_user_memory, user_id)
                turn = user_mem.new_turn()
                turn.user_input = str(data.get("text", ""))
                
                current_time = data.get("time")
                if not current_time:
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] 使用者輸入: {turn.user_input}")

                # --- Task 1: 語意解析 ---
                task = "task1"
                messages_task1, _ = await loop.run_in_executor(
                    None, lambda: GlobalState.builder.build_messages(
                        memory=user_mem, mode=task, system_prompt=TASK_PROMPTS[task], context_time=current_time
                    )
                )

                GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] === TASK 1 推論中 ===")
                GlobalState.logger.debug(f"[PID:{GlobalState.pid}] [SID:{user_id}] Task 1 Message Builder 輸出:\n{json.dumps(messages_task1, indent=2, ensure_ascii=False)}")
                raw_json_output = ""
                print(f"[PID:{GlobalState.pid}] [SID:{user_id}] Task 1 即時推論: ", end="", flush=True)
                async for chunk in infer(messages_task1, mode=task):
                    raw_json_output += chunk
                    print(chunk, end="", flush=True)
                print() # 推論結束後換行
                
                GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] Task 1 模型原始輸出:\n{raw_json_output}")

                # 魯棒性高的 JSON 解析
                try:
                    clean_json = raw_json_output.replace("```json", "").replace("```", "").strip()
                    semantic_dict = repair_loads(clean_json)
                    if not isinstance(semantic_dict, dict): semantic_dict = {}
                except Exception:
                    semantic_dict = {}

                turn.json_output = json.dumps(semantic_dict, ensure_ascii=False)
                GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] Task 1 解析後結構化結果:\n{turn.json_output}")

                # --- 決定路徑：Task 2 (追問) 或 Task 3 (檢索) ---
                datas = None
                is_search_error = False
                if not semantic_dict or semantic_dict.get("follow_up") is True:
                    task = "task2"
                else:
                    task = "task3"
                    query_id = semantic_dict.get("query_id")
                    if query_id:
                        page = semantic_dict.get("page", 1)
                        api_url = f"{PAGE_SEARCH_API_URL}?search_ssid={query_id}&page={page}"
                        method = "GET"
                    else:
                        api_url = NEW_SEARCH_API_URL
                        method = "POST"
                        json_payload = {
                            "s_id": user_id,
                            "u_time": data.get("time"),
                            "user_location": {
                                "lat": data.get("gps", {}).get("lat"),
                                "lng": data.get("gps", {}).get("lng")
                            },
                            **semantic_dict
                        }

                    GlobalState.logger.debug(f"[PID:{GlobalState.pid}] [SID:{user_id}] Task 3 發送 API 請求: URL={api_url}, Method={method}, Payload={json.dumps(json_payload, ensure_ascii=False) if method == 'POST' else None}")
                    # --- 執行資料檢索 ---
                    try:
                        if method == "GET":
                            resp = await GlobalState.client.get(api_url)
                        else:
                            resp = await GlobalState.client.post(api_url, json=json_payload)

                        if resp.status_code == 200:
                            api_res = resp.json()
                            results = api_res.get("data", {}).get("final_results", [])
                            
                            new_ssid = api_res.get("data", {}).get("pagination", {}).get("search_ssid")
                            if new_ssid: turn.query_id = new_ssid
                            
                            # ==========================================
                            # 💡 核心變更：雙軌資料提取與組合 (無論有無結果都提取)
                            # ==========================================
                            
                            # 軌道 1：提取全局元數據 (Metadata)
                            metadata = {}
                            for g_path in GLOBAL_REQUIRED_FIELDS:
                                val = get_value_by_path(api_res, g_path)
                                if val is not None:
                                    # 將路徑最後一段作為 Key (例：data.is_fallback -> is_fallback)
                                    key_name = g_path.split('.')[-1] 
                                    metadata[key_name] = val

                            # 軌道 2：決定餐廳需要抓取的欄位，並清洗列表
                            needed_keys = get_required_fields(semantic_dict)
                            GlobalState.logger.debug(f"[PID:{GlobalState.pid}] [SID:{user_id}] 餐廳動態與常數欄位: {needed_keys}")
                            
                            cleaned_restaurants = []
                            
                            # 準備給前端 GUI 渲染用的 Metadata (只保留 type 與 pid)
                            gui_metadata = {}
                            
                            if results:
                                pids = [item.get("id") for item in results if "id" in item]
                                
                                # 💡 新增：將 PID 寫入 Log 並顯示於終端機
                                GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] 推薦店家 PIDs: {pids}")
                                print(f"\n📍 [推薦店家 IDs]: {pids}")
                                
                                gui_metadata["type"] = "pid"
                                gui_metadata["pid"] = pids
                                
                                for item in results:
                                    extracted = {}
                                    for path_key in needed_keys:
                                        val = get_value_by_path(item, path_key)
                                        if val is not None:
                                            extracted[path_key] = val
                                    cleaned_restaurants.append(extracted)

                            # 💡 確保 test_gui.py 能正確捕捉隱藏資訊 (只回傳需要的欄位)
                            if gui_metadata:
                                yield f"{json.dumps(gui_metadata, ensure_ascii=False)}\n"

                            # 最終合併：組合出完美的 LLM Context，即使沒有店家，LLM 也能根據 status 等 metadata 回應
                            final_context = {
                                "search_metadata": metadata,
                                "restaurants": cleaned_restaurants
                            }
                            datas = json.dumps(final_context, indent=2, ensure_ascii=False)
                            GlobalState.logger.debug(f"[PID:{GlobalState.pid}] [SID:{user_id}] Task 3 API 檢索與清洗結果:\n{datas}")
                        else:
                            is_search_error = True
                    except Exception as e:
                        GlobalState.logger.error(f"[PID:{GlobalState.pid}] [SID:{user_id}] 檢索失敗: {e}")
                        is_search_error = True

                if is_search_error:
                    response_text = "真的很不好意思啦～目前系統好像有點秀逗連不上，要不要等等再試一次看看？"
                    yield response_text
                    turn.response_output = response_text
                    GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] 檢索失敗，跳過 Task 3 推論，直接回傳寫死訊息")
                    return

                # --- Task 2/3: 生成最終回覆 ---
                GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] === {task.upper()} 推論中 ===")
                messages_final, _ = await loop.run_in_executor(
                    None, lambda: GlobalState.builder.build_messages(
                        datas=datas if task == "task3" else None,
                        memory=user_mem,
                        mode=task,
                        system_prompt=TASK_PROMPTS[task],
                        context_time=current_time
                    )
                )
                GlobalState.logger.debug(f"[PID:{GlobalState.pid}] [SID:{user_id}] {task.upper()} Message Builder 輸出:\n{json.dumps(messages_final, indent=2, ensure_ascii=False)}")

                print(f"[PID:{GlobalState.pid}] [SID:{user_id}] {task.upper()} 即時推論: ", end="", flush=True)
                async for chunk in infer(messages_final, mode=task):
                    response_text += chunk
                    print(chunk, end="", flush=True)
                    yield chunk
                print() # 推論結束後換行
                
                turn.response_output = response_text
                GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] {task.upper()} 模型輸出結果:\n{response_text}")
                GlobalState.logger.info(f"[PID:{GlobalState.pid}] [SID:{user_id}] 生成結束")

        except asyncio.CancelledError:
            if turn: turn.response_output = response_text + " [已終止]"
            GlobalState.logger.warning(f"[PID:{GlobalState.pid}] [SID:{user_id}] 任務取消")
        except Exception as e:
            GlobalState.logger.error(f"[PID:{GlobalState.pid}] [SID:{user_id}] 系統故障: {e}", exc_info=True)
            yield f"\n[系統錯誤]: {str(e)}"
        finally:
            GlobalState.active_tasks.pop(user_id, None)
            if not queue_cleared and not request_queue.empty():
                await request_queue.get()
                request_queue.task_done()

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/stop")
async def stop_generation(request: Request):
    """終止指定任務"""
    data = await request.json()
    user_id = data.get("sid")
    if user_id in GlobalState.active_tasks:
        GlobalState.active_tasks[user_id].cancel()
        return {"status": "success", "message": "Task cancelled"}
    return JSONResponse(status_code=404, content={"status": "error", "message": "Task not found"})


@app.post("/free_memory")
async def free_memory(request: Request):
    """清除對話記憶體"""
    data = await request.json()
    user_id = data.get("sid")
    if not user_id: return JSONResponse(status_code=400, content={"message": "Missing sid"})
    
    if user_id in GlobalState.active_tasks:
        GlobalState.active_tasks[user_id].cancel()

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, GlobalState.manager.delete_user_memory, user_id)
    return PlainTextResponse("OK")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host=os.getenv("API_SERVER_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_SERVER_PORT", 5000)),
        log_level="info"
    )