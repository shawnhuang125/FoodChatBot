#!/bin/bash
set -e

# 檢查模型目錄是否存在且不為空
# 假設你的模型檔案通常至少包含 config.json 或 model.safetensors
if [ ! -f "/code/m3_food_finetuned/config.json" ]; then
    echo "偵測到模型缺失，正在從 HuggingFace 下載 BGE-M3..."
    python3 -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='BAAI/bge-m3', local_dir='/code/m3_food_finetuned')"
else
    echo "模型已存在，跳過下載步驟。"
fi

# 執行原本的應用程式
exec python run.py