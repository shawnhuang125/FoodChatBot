# 使用輕量級的 Python 3.10 作為基底
FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 💡 核心修正：強制 Python 即時輸出日誌到標準輸出（stdout），不進行記憶體緩衝
# 這樣你在 docker logs 才能即時看到「傳送出去與接收進來」的完整封包數據！
ENV PYTHONUNBUFFERED=1

# 先複製依賴清單並安裝，利用 Docker 快取機制加速後續建置
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製所有程式碼到容器內
COPY . .

# 宣告對外開放的 Port (對應你程式的 GATEWAY_PORT = 5000)
EXPOSE 5000

# 啟動指令 (假設你的檔案叫 main.py，入口點是 combined_app)
CMD ["python", "main.py"]
