# 1. 使用標準輕量 Python 3.10 映像檔 (自動適應 Windows x86_64 架構)
FROM python:3.10-slim

# 避免互動提示
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# 2. 安裝基礎編譯與相依套件 (包含 curl 用於健康檢查)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 3. 設定工作目錄
WORKDIR /code

# 4. 先複製 requirements.txt 並安裝相依套件 (利用 Docker 快取機制)
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn && \
    pip install --no-cache-dir -r /code/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn

# 5. 複製專案原始碼進容器
COPY . /code

# 6. 修復 entrypoint.sh 執行權限與換行符號問題 (Windows 轉 Linux 換行符號必備)
RUN sed -i 's/\r$//' /code/entrypoint.sh && \
    chmod +x /code/entrypoint.sh

# 開放指定 Port 5004
EXPOSE 5004

# 使用 ENTRYPOINT 執行啟動腳本
ENTRYPOINT ["/code/entrypoint.sh"]