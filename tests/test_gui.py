import streamlit as st
import httpx
import json
import asyncio
import os
from datetime import datetime, date
from dotenv import load_dotenv

# ==========================================
# ⚙️ 載入環境變數與初始設定
# ==========================================
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

api_host = os.getenv("API_SERVER_HOST", "127.0.0.1")
if api_host == "0.0.0.0":
    api_host = "127.0.0.1" # Streamlit 端需要綁定真實 IP 或 localhost
api_port = os.getenv("GUI_API_PORT", "5000") # Streamlit GUI 使用專屬端口
DEFAULT_BACKEND_URL = f"http://{api_host}:{api_port}"
GUI_DEFAULT_SID = os.getenv("GUI_DEFAULT_SID", "test_user_001")
GUI_DEFAULT_LAT = float(os.getenv("GUI_DEFAULT_LAT", 23.0016))
GUI_DEFAULT_LNG = float(os.getenv("GUI_DEFAULT_LNG", 120.2528))
GUI_API_TIMEOUT = float(os.getenv("GUI_API_TIMEOUT", 60.0))

st.set_page_config(page_title="AI Bot 專業測試儀表板", layout="wide", page_icon="🤖")
st.title("🤖 AI Bot 整合除錯儀表板")

# ==========================================
# 💾 初始化 Session State
# ==========================================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "sid" not in st.session_state:
    st.session_state.sid = GUI_DEFAULT_SID

# ==========================================
# 🎛️ 側邊欄：設定與模擬器
# ==========================================
with st.sidebar:
    st.header("🔌 連線設定")
    backend_url = st.text_input("後端 API 位址", value=DEFAULT_BACKEND_URL)
    user_id = st.text_input("使用者 ID (sid)", value=st.session_state.sid)
    st.session_state.sid = user_id
    
    st.divider()
    
    st.header("📍 模擬環境設定")
    sim_date = st.date_input("模擬日期", value=date.today())
    sim_time = st.time_input("模擬時間", value=datetime.now().time())
    sim_lat = st.number_input("Lat (緯度 - 預設崑山科大)", value=GUI_DEFAULT_LAT, format="%.4f")
    sim_lng = st.number_input("Lng (經度 - 預設崑山科大)", value=GUI_DEFAULT_LNG, format="%.4f")
    # 組合為系統認可的字串格式
    current_sim_datetime = datetime.combine(sim_date, sim_time).strftime("%Y-%m-%d %H:%M:%S")
    
    st.divider()
    
    st.header("🛠️ 功能控制")
    if st.button(" 停止生成 (Stop)", use_container_width=True):
        try:
            resp = httpx.post(f"{backend_url}/stop", json={"sid": user_id})
            st.toast(resp.json().get("message", "已發送停止請求"))
        except Exception as e:
            st.error(f"❌ 連線失敗: {e}")

    if st.button("🗑️ 清除記憶 (Free Memory)", use_container_width=True, type="primary"):
        try:
            resp = httpx.post(f"{backend_url}/free_memory", json={"sid": user_id})
            if resp.status_code == 200:
                st.session_state.messages = []
                st.success("✨ 後端記憶體已釋放，對話紀錄已清除")
                st.rerun()
        except Exception as e:
            st.error(f"❌ 連線失敗: {e}")

# ==========================================
# 💬 介面渲染：顯示歷史訊息
# ==========================================
def render_message(msg):
    avatar = "🧑‍💻" if msg["role"] == "user" else "🤖"
    with st.chat_message(msg["role"], avatar=avatar):
        metadata = msg.get("metadata", {})
        if metadata:
            # 獨立渲染 PID 卡片
            if "pid" in metadata and metadata["pid"]:
                st.info(f"📍 **推薦店家 IDs**: `{metadata['pid']}`")
            
            # 將純技術欄位封裝進折疊面板
            tech_data = {k: v for k, v in metadata.items() if k not in ["type", "pid"]}
            if tech_data:
                with st.expander("🛠️ 技術診斷資訊 (Metadata)", expanded=False):
                    st.json(tech_data)

        st.markdown(msg["content"])

for message in st.session_state.messages:
    render_message(message)

# ==========================================
# 🚀 主流程：使用者輸入與串流請求
# ==========================================
if prompt := st.chat_input("請輸入測試訊息..."):
    # 1. 顯示並儲存使用者訊息
    user_msg = {"role": "user", "content": prompt}
    st.session_state.messages.append(user_msg)
    render_message(user_msg)

    # 2. 構建即時 Payload
    payload = {
        "sid": user_id,
        "text": prompt,
        "time": current_sim_datetime,
        "lat": float(sim_lat), 
        "lng": float(sim_lng)
    }

    # 3. 處理 AI 串流回覆
    with st.chat_message("assistant", avatar="🤖"):
        metadata_dict = {}
        f_resp = ""
        
        # 使用狀態容器包裹處理過程，提供更好的 UX
        with st.status("🤖 解析意圖中...", expanded=True) as status_container:
            st.write("📡 發送請求至後端...")
            
            async def fetch_stream():
                response_text = ""
                buffer = ""
                first_token_received = False
                
                try:
                    # timeout 與環境變數相配合
                    async with httpx.AsyncClient(timeout=GUI_API_TIMEOUT) as client:
                        async with client.stream("POST", f"{backend_url}/text_bot_input", json=payload) as response:
                            if response.status_code != 200:
                                st.error(f"❌ 後端伺服器回應錯誤: {response.status_code}")
                                return response_text
                            
                            async for chunk in response.aiter_text():
                                if not first_token_received:
                                    first_token_received = True
                                    status_container.update(label="💬 檢索成功，LLM 組織語言中...", state="running")
                                    
                                buffer += chunk
                                
                                # [強健解析] 提取隱藏的 __METADATA__ 行，確保不會因為 chunk 斷裂而破壞 JSON
                                while "\n" in buffer and buffer.startswith("__METADATA__"):
                                    line, buffer = buffer.split("\n", 1)
                                    meta_str = line.replace("__METADATA__", "")
                                    try:
                                        meta = json.loads(meta_str)
                                        metadata_dict.update(meta)
                                    except Exception:
                                        pass
                                        
                                # 顯示一般的生成文字輸出
                                if not buffer.startswith("__METADATA__"):
                                    response_text += buffer
                                    placeholder.markdown(response_text + "▌")
                                    buffer = ""
                                    
                            # 將最後剩下的安全緩衝區清空
                            if buffer and not buffer.startswith("__METADATA__"):
                                response_text += buffer
                                
                            placeholder.markdown(response_text)
                            status_container.update(label="✅ 生成完成", state="complete", expanded=False)
                            return response_text

                except httpx.ReadTimeout:
                    st.error("⏳ API 請求超時，後端伟服器未能在預期時間內回應。")
                    status_container.update(label="❌ 連線超時", state="error", expanded=True)
                except Exception as e:
                    st.error(f"❌ 連線失敗或發生系統錯誤: {str(e)}")
                    status_container.update(label="❌ 系統錯誤", state="error", expanded=True)

                return response_text

        # 💡 將 placeholder 與異步執行移出 status 容器，這樣串流文字才會顯示在外部的主要聊天區域，而不會被折疊隱藏
        placeholder = st.empty()
        
        # 執行異步抓取
        f_resp = asyncio.run(fetch_stream())
        
        # 渲染最後抓取到的技術指標與 PID (在生成完成後展示)
        if metadata_dict:
            if "pid" in metadata_dict and metadata_dict["pid"]:
                st.info(f"📍 **推薦店家 IDs**: `{metadata_dict['pid']}`")
            
            tech_data = {k: v for k, v in metadata_dict.items() if k not in ["type", "pid"]}
            if tech_data:
                with st.expander("🛠️ 技術診斷資訊 (Metadata)", expanded=False):
                    st.json(tech_data)
        
        # 4. 將結果存入記憶
        st.session_state.messages.append({
            "role": "assistant", 
            "content": f_resp,
            "metadata": metadata_dict
        })

if __name__ == "__main__":
    pass