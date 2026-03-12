import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler

def setup_logger(name="PlaceService"):
    logger = logging.getLogger(name)
    
    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.INFO)

    # 統一的日誌格式
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. 設定終端機輸出 (Console)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. 設定按日期滾動的檔案輸出 (File)
    log_dir = "./log"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_filename = os.path.join(log_dir, "app.log")
    
    # TimedRotatingFileHandler 參數說明：
    # when="midnight": 每天午夜自動切換檔案
    # interval=1: 每 1 天觸發一次
    # backupCount=30: 保留最近 30 天的日誌，舊的會自動刪除
    # encoding="utf-8": 確保中文不亂碼
    file_handler = TimedRotatingFileHandler(
        log_filename, 
        when="midnight", 
        interval=1, 
        backupCount=30, 
        encoding="utf-8"
    )
    
    # 設定檔案名稱的後綴格式 (例如 app.log.2026-02-25)
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# 實例化全域 logger
logger = setup_logger()