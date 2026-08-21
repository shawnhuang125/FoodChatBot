
# app/models/search_dto.py
from dataclasses import dataclass, field
from typing import List, Optional,Any

@dataclass
class VectorSearchResult:
    """
    這是搜尋結果的標準資料格式 (DTO)。
    """
    id: Any  #  original_id 是字串
    name: str = "Unknown"
    cuisine_type: List[str] = field(default_factory=list)
    food_type: List[str] = field(default_factory=list)
    flavor: List[str] = field(default_factory=list)
    facility_tags: List[str] = field(default_factory=list)
    service_tags: List[str] = field(default_factory=list)
    review_summary: str = ""
    
    # 加上這行來接收 Qdrant 的相似度分數
    score: float = 0.0

    def get_short_review(self):
        return self.review_text[:50] + "..." if len(self.review_text) > 50 else self.review_text