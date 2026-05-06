# -*- coding: utf-8 -*-
import asyncio
import json
import os
import sys
import logging
import time
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
import socketio
import httpx
import uvicorn
import redis.asyncio as redis 

# ==========================================
# ⚙️ 系統設定與底層優化 (OS 判斷與日誌)
# ==========================================
if sys.platform != 'win32':
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        LOOP_TYPE = "uvloop"
    except ImportError:
        LOOP_TYPE = "asyncio"
else:
    LOOP_TYPE = "asyncio" 

def setup_app_logging():
    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s | PID:%(process)d | %(message)s', datefmt='%H:%M:%S') 
    file_handler = RotatingFileHandler('app.log', maxBytes=5*1024*1024, backupCount=10, encoding='utf-8')
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

setup_app_logging()

# 常數設定
TEXT_BOT_API_URL = os.getenv("TEXT_BOT_API_URL", "http://192.168.1.116:5000/text_bot_input")
TEXT_BOT_API_URL_1 = os.getenv("TEXT_BOT_API_URL_1", "http://192.168.1.116:5000/free_memory")
PLACE_SEARCH_URL = os.getenv("PLACE_SEARCH_URL", "http://192.168.1.118:5004/place_search")

GATEWAY_HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", 5000)) # 注意 Port 需要是整數
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

redis_db = None             
http_client = None     

# ==========================================
# 🧱 第四層：底層儲存與外部通訊 (Storage & Clients)
# ==========================================
async def setup_clients():
    """初始化 Redis 與 HTTPX 連線池"""
    global redis_db, http_client
    redis_db = redis.from_url(REDIS_URL, decode_responses=True)
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
    http_client = httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(20.0, read=None))

async def close_clients():
    """關閉底層連線資源"""
    await http_client.aclose() 
    await redis_db.aclose()

# ==========================================
# 🛡️ 第二層：狀態管理與安全監控層 (Security & State)
# ==========================================
async def system_self_healing_lock():
    """利用 Redis NX 分散式鎖進行系統初始化自癒"""
    try:
        is_master = await redis_db.set("gateway_init_lock", "1", nx=True, ex=5)
        if is_master:
            await redis_db.delete("active_sids") 
            logging.info("✨ [系統自癒] 資源紀錄檢查完成。")
    except Exception as e:
        logging.error(f"❌ 初始化失敗: {e}")

async def check_rate_limit(client_ip: str) -> bool:
    """IP 頻率限制 (2秒內限連線一次)"""
    return await redis_db.set(f"ip_limit:{client_ip}", "1", nx=True, ex=2)

async def register_session(sid: str):
    """註冊 Redis 會話與心跳"""
    await redis_db.hset(f"session:{sid}", "last_seen", int(time.time()))
    await redis_db.sadd("active_sids", sid)

async def unregister_session(sid: str):
    """註銷 Redis 會話資源"""
    await redis_db.delete(f"session:{sid}")
    await redis_db.srem("active_sids", sid)

async def update_heartbeat(sid: str) -> bool:
    """更新活躍連線的心跳時間"""
    if await redis_db.sismember("active_sids", sid):
        await redis_db.hset(f"session:{sid}", "last_seen", int(time.time()))
        return True
    return False

async def monitor_loop():
    """背景自癒巡檢協程"""
    while True:
        await asyncio.sleep(60)
        now = int(time.time())
        try:
            active_sids = await redis_db.smembers("active_sids")
            active_rooms = list(sio.manager.rooms.get('/', {}).keys())

            for sid in active_sids:
                session_data = await redis_db.hgetall(f"session:{sid}")
                if not session_data:
                    await redis_db.srem("active_sids", sid)
                    continue

                last_seen = int(session_data.get("last_seen", now))
                if sid not in active_rooms:
                    logging.warning(f"♻️ [殭屍回收] SID {sid} 幽靈連線，強制清理")
                    await gw_on_disconnect(sid)
                    continue
                
                if now - last_seen > 600:
                    logging.warning(f"⏰ [超時回收] SID {sid} 閒置過久，強制中斷。")
                    await sio.disconnect(sid) 
        except Exception:
            pass

# ==========================================
# 🧠 第三層：核心處理與封裝組件 (Core Processing)
# ==========================================
def parse_and_intercept_commands(data: any):
    """指令攔截與 Payload 封裝"""
    is_stop, is_reset = False, False
    payload = {}

    if isinstance(data, dict):
        payload = data.copy() 
        action = payload.get("action")
        if action == "stop": is_stop = True
        elif action == "reset": is_reset = True
    else:
        data_str = str(data)
        if data_str == "STOP_TASK": is_stop = True
        elif data_str == "RESET_SESSION": is_reset = True
        else: payload = {"text": data_str}
        
    return is_stop, is_reset, payload

async def notify_ai_backend(sid: str, reason: str):
    """通知遠端 AI 伺服器釋放記憶體"""
    try:
        await http_client.post(TEXT_BOT_API_URL_1, json={"sid": sid, "reason": reason}, timeout=5.0)
    except Exception:
        pass

async def relay_ai_stream(sid: str, payload: dict):
    """非同步串流中繼器與 JSON 容錯解析引擎"""
    payload["sid"] = sid 
    try:
        logging.info(f"📡 [轉發] 準備透過 HTTP 連線池轉發至 AI Bot")
        async with http_client.stream("POST", TEXT_BOT_API_URL, json=payload) as resp:
            if resp.status_code == 200:
                logging.info("🌊 [接收] 開始接收打字機資料...")
                async for chunk in resp.aiter_text():
                    if not chunk: continue
                    if not await redis_db.sismember("active_sids", sid): break # 離線斷號保護
                    
                    chunk_safe = str(chunk)
                    print(chunk_safe, end="", flush=True)
                    
                    # JSON 容錯解析引擎
                    try:
                        json_payload = json.loads(chunk_safe)
                        await sio.emit("chat_stream", json_payload, to=sid)
                    except json.JSONDecodeError:
                        await sio.emit("chat_stream", {"text": chunk_safe}, to=sid)

                print("\n") 
                if await redis_db.sismember("active_sids", sid):
                    await sio.emit("chat_stream", {"done": True}, to=sid)
                    logging.info("✅ [完成] 已發送 done: true 給前端")
            else:
                logging.error(f"❌ [錯誤] 後端伺服器異常 ({resp.status_code})")
                await sio.emit("chat_stream", {"text": f"系統異常 ({resp.status_code})", "done": True}, to=sid)

    except Exception as e:
        logging.error(f"❌ [Gateway 異常] 轉發崩潰: {e}")
        if await redis_db.sismember("active_sids", sid):
            await sio.emit("chat_stream", {"text": "Gateway 異常", "done": True}, to=sid)

# ==========================================
# 🌐 第一層：對外通訊與路由接口 (API & Events)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命週期管理 (負責啟動第二、第四層模組)"""
    await setup_clients()
    await system_self_healing_lock()
    monitor_task = asyncio.create_task(monitor_loop())
    yield 
    monitor_task.cancel()
    await close_clients()

app = FastAPI(lifespan=lifespan)  
client_manager = socketio.AsyncRedisManager(REDIS_URL)
sio = socketio.AsyncServer(async_mode='asgi', client_manager=client_manager, cors_allowed_origins="*")

# ----------------- HTTP 業務轉發 -----------------
@app.post("/search_result", summary="數據轉發中繼", tags=["Data Routing"])
async def forward_search_result(request: Request):
    logging.info("\n" + "▼"*50)
    logging.info("🔍 [檢索觸發] 收到 /search_result 請求")
    try:
        payload = await request.json()
        response = await http_client.post(PLACE_SEARCH_URL, json=payload)
        
        if response.status_code == 200:
            logging.info(f"📤 [檢索成功] 已從資料庫取得結果")
            logging.info("▲"*50 + "\n")
            return response.json()
        else:
            return {"error": "forwarding failed", "status_code": response.status_code}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ----------------- Socket.IO 事件 -----------------
@sio.on("connect")  
async def gw_on_connect(sid, environ, auth=None):
    client_ip = environ.get('REMOTE_ADDR', 'unknown_ip')
    
    # 呼叫第二層：IP 限流模組
    if not await check_rate_limit(client_ip):
        logging.warning(f"🛡️ [頻率限制] IP {client_ip} 連線太頻繁。")
        return False

    # 呼叫第二層：註冊會話模組
    await register_session(sid)
    logging.info(f"🔗 App 連線成功！ SID: {sid}")

@sio.on("text_input")  
async def gw_text_input(sid, data):
    # 呼叫第二層：心跳更新
    await update_heartbeat(sid)
    logging.info("\n" + "▼"*50)
    logging.info(f"📥 [接收前端] 收到來自 SID: {sid} 的請求")
    
    # 呼叫第三層：指令攔截與封裝
    is_stop, is_reset, payload = parse_and_intercept_commands(data)

    if is_stop:
        logging.info(f"⏹️ [停止指令] 通知 AI (靜默模式)...")
        await notify_ai_backend(sid, "user_stop")
        await sio.emit("chat_stream", {"done": True}, to=sid)
        logging.info("▲"*50 + "\n")
        return 

    if is_reset:
        logging.info(f"🔄 [重置指令] 通知 AI (靜默模式)...")
        await notify_ai_backend(sid, "user_reset")
        logging.info("▲"*50 + "\n")
        return 

    # 呼叫第三層：非同步串流轉發
    await relay_ai_stream(sid, payload)
    logging.info("▲"*50 + "\n")

@sio.on("disconnect")
async def gw_on_disconnect(sid):
    logging.info(f"💀 [離線] SID {sid} 斷線，回收資源")
    await notify_ai_backend(sid, "disconnect")
    # 呼叫第二層：註銷會話模組
    await unregister_session(sid)

# ----------------- HTTP 維運管理 -----------------
@app.get("/status", summary="取得網關即時狀態", tags=["System Management"])
async def get_status():
    try:
        active_sids = await redis_db.smembers("active_sids")
        return {"gateway_status": "online", "total_active_users": len(active_sids)}
    except Exception as e: return {"error": str(e)}

@app.get("/logs", summary="檢視最近系統日誌", tags=["System Management"])
async def get_logs():
    try:
        with open("app.log", "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines()[-200:] if l.strip()]
        return {"logs": lines}
    except Exception as e: return {"error": str(e)}

@app.post("/force_cleanup", summary="強制清理全域快取資源", tags=["System Management"])
async def force_cleanup():
    try:
        active_sids = await redis_db.smembers("active_sids")
        for sid in active_sids: await notify_ai_backend(sid, "force_cleanup")
        await redis_db.delete("active_sids")
        return {"status": "success", "cleaned_users": len(active_sids)}
    except Exception as e: return {"error": str(e)}

combined_app = socketio.ASGIApp(sio, app) 

# ==========================================
# 🚀 執行入口 (Main)
# ==========================================
if __name__ == "__main__":
    print("\n" + "═"*60)
    print(" 🚀 API Gateway [四層模組化完美版]")
    print(f" 📍 監聽網址: http://0.0.0.0:{GATEWAY_PORT}")
    print(f" 📊 管理後台: http://127.0.0.1:{GATEWAY_PORT}/docs")
    print(" ═"*60 + "\n")
    
    if sys.platform == 'win32':
        uvicorn.run(combined_app, host=GATEWAY_HOST, port=GATEWAY_PORT, loop=LOOP_TYPE, log_level="warning")
    else:
        uvicorn.run("main:combined_app", host=GATEWAY_HOST, port=GATEWAY_PORT, workers=4, loop=LOOP_TYPE, log_level="warning")