import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo # Python 3.9+ 適用
from dotenv import load_dotenv

load_dotenv()

LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "app.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# --- 新增時區設定 ---
def taiwan_time(*args):
    """ 強制將日誌時間轉換為台北時區 """
    return datetime.now(ZoneInfo("Asia/Taipei")).timetuple()

def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    
    if not logger.hasHandlers():
        # 讓 logger 實體可以接收所有級別的日誌
        logger.setLevel(logging.DEBUG)
        
        # 關鍵點：修改 Formatter 的時間轉換函數
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s', 
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        # 告訴 logging 模組：不要用系統時間，用我指定的台灣時間
        formatter.converter = taiwan_time

        # 輸出到檔案 (記錄所有詳細的 DEBUG 日誌)
        file_handler = logging.FileHandler(LOG_FILE_PATH, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # 輸出到終端機 (依照環境變數，通常為 INFO，只顯示重要流程)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger