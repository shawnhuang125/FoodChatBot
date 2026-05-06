# app/utils/app_logger.py
import logging
import os
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from queue import Queue

class AppLogger:
    def __init__(self):
        self.log_dir = "logs"
        self.log_file = os.path.join(self.log_dir, "app.log")
        self.log_queue = Queue(-1)
        self.listener = None

    def setup_logging(self):
        """初始化日誌系統，接管全域日誌"""
        # 1. 確保目錄存在
        os.makedirs(self.log_dir, exist_ok=True)

        # 2. 設定格式
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

        # 3. 建立後端 Handlers (真正負責寫入的)
        file_handler = TimedRotatingFileHandler(
            self.log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.suffix = "%Y-%m-%d"

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)

        # 4. 建立監聽器 (從 Queue 搬運日誌到 Handlers)
        self.listener = QueueListener(
            self.log_queue, file_handler, stream_handler, respect_handler_level=True
        )
        self.listener.start()

        # 5. 配置 Root Logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        
        # 清除舊有的 Handler (包含 Uvicorn 預設)
        if root_logger.hasHandlers():
            root_logger.handlers.clear()

        # 唯一的入口：QueueHandler
        queue_handler = QueueHandler(self.log_queue)
        root_logger.addHandler(queue_handler)

        # 讓 uvicorn 也走我們的非同步佇列
        for _log in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
            _logger = logging.getLogger(_log)
            _logger.handlers = [queue_handler]
            _logger.propagate = False # 避免重複列印

        logging.info("[Logger] 非同步日誌系統初始化完成。")

    def stop_logging(self):
        """關閉監聽器，確保剩餘日誌寫入"""
        if self.listener:
            logging.info("[Logger] 正在關閉日誌監聽器...")
            self.listener.stop()

# 建立單例供外部使用
app_log_manager = AppLogger()
logger = logging.getLogger("FastAPIApp")