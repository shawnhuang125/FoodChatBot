import os
import threading
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()
MAX_TURNS_CONFIG = int(os.getenv("MEMORY_MAX_TURNS", 3))

class Turn:
    """ 紀錄單次對話 (Turn) 內的互動細節，涵蓋各個 Task 階段產出的資料 """
    def __init__(
        self,
        turn_id: Optional[int] = None,
        user_input: Optional[str] = None,
        json_output: Optional[Dict[str, Any]] = None,
        response_output: Optional[str] = None,
        query_id: Optional[str] = None
    ):
        self.turn_id = turn_id
        self.user_input = user_input
        self.json_output = json_output
        self.response_output = response_output
        self.query_id = query_id

    def to_dict(self):
        return {
            "turn_id": self.turn_id,
            "user_input": self.user_input,
            "json_output": self.json_output,
            "response_output": self.response_output,
            "query_id": self.query_id
        }
    
class UserMemory:
    """ 使用者個人的歷史對話記憶庫，利用 Lock 保證並發時的安全性 """
    def __init__(self, user_id: str, max_turns: int = MAX_TURNS_CONFIG):
        self.user_id = user_id
        self.turns: List[Turn] = []
        self.max_turns = max_turns 
        self.next_turn_id = 1
        self.lock = threading.Lock()
    
    def new_turn(self) -> Turn:
        with self.lock:
            if len(self.turns) >= self.max_turns:
                self.turns.pop(0)
            turn = Turn(self.next_turn_id)
            self.next_turn_id += 1
            self.turns.append(turn)
            return turn
    
    def get_all_turns(self) -> List[Turn]:
        with self.lock:
            return list(self.turns)
    
class MemoryManager:
    """ 對話記憶管理器，集中管理所有使用者的記憶庫實例 """
    def __init__(self):
        self.users: Dict[str, UserMemory] = {}
        self.lock = threading.Lock()

    def get_user_memory(self, user_id: str) -> UserMemory:
        with self.lock:
            if user_id not in self.users:
                self.users[user_id] = UserMemory(user_id)
            return self.users[user_id]
    
    def delete_user_memory(self, user_id: str):
        with self.lock:
            if user_id in self.users:
                del self.users[user_id]