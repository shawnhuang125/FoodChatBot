#!/bin/bash
set -e

# 優先讀取環境變數，若無則預設為 /models/bge_m3
TARGET_MODEL_PATH="${EMBEDDING_MODEL_PATH:-/models/bge_m3}"

echo "正在檢查模型路徑: $TARGET_MODEL_PATH"

# 檢查掛載路徑下是否存在模型核心檔案
if [ ! -f "$TARGET_MODEL_PATH/config.json" ]; then
    echo "=================================================="
    echo "錯誤：未在 $TARGET_MODEL_PATH 偵測到模型檔案！"
    echo "請確認 docker-compose.yml 的 volumes 是否正確對應至此路徑。"
    echo "=================================================="
    exit 1
else
    echo "模型檢驗通過 ($TARGET_MODEL_PATH)，準備啟動 FastAPI 服務..."
fi

# 啟動應用程式
exec python run.py