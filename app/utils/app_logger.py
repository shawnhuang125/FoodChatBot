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
        """關閉非同步日誌監聽器（防卡死與消警告強化版）"""
        if hasattr(self, 'listener') and self.listener:
            try:
                print("[Logger] 正在關閉日誌監聽器...")
                
                # 1. 使用 getattr 動態取得私有屬性 _sentinel（規避 Pylance 警告）
                sentinel = getattr(self.listener, "_sentinel", None)
                if sentinel is not None:
                    try:
                        self.listener.queue.put_nowait(sentinel)
                    except Exception:
                        pass
                
                # 2. ⚡ 給予背景執行緒 0.5 秒 Timeout，絕不無限期死等！
                listener_thread = getattr(self.listener, "_thread", None)
                if listener_thread and listener_thread.is_alive():
                    listener_thread.join(timeout=0.5)
                
                print("[Logger] 日誌監聽器已安全釋放。")
            except Exception as e:
                print(f"[Logger Shutdown Warning] 關閉監聽器時發生非致命例外: {e}")
            finally:
                self.listener = None

# 建立單例供外部使用
app_log_manager = AppLogger()
logger = logging.getLogger("FastAPIApp")