# 使用輕量級的 Python 3.10 作為基底
FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 先複製依賴清單並安裝，利用 Docker 快取機制加速後續建置
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製所有程式碼到容器內
COPY . .

# 宣告對外開放的 Port (對應你程式的 GATEWAY_PORT = 5000)
EXPOSE 5000

# 啟動指令 (假設你的檔案叫 main.py，入口點是 combined_app)
# 改成這樣（拿掉 workers 參數，預設就是單一進程）：
CMD ["uvicorn", "main:combined_app", "--host", "0.0.0.0", "--port", "5000", "--loop", "uvloop"]