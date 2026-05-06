FROM python:3.9-slim

WORKDIR /app

# 1. 安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. 複製程式碼
COPY . .

# 3. 建立必要的資料夾
RUN mkdir -p logs

# 4. 開放 Port (FastAPI 預設也常用 8000，這裡維持你原本的 5003)
EXPOSE 5003

# 5. 啟動指令：改用 uvicorn 才能支援 FastAPI 的非同步特性
# 假設你的程式碼主程式是 main.py，裡面定義了 app = FastAPI()
CMD ["uvicorn", "run:app", "--host", "0.0.0.0", "--port", "5003"]