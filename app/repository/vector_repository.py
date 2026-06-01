# app/repository/vector_repository.py
from typing import List, Any
from app.models.search_dto import VectorSearchResult
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from app.config import Config
from app.utils.db import get_qdrant_client
from app.utils.app_logger import logger
import asyncio


class VectorRepository:
    def __init__(self, use_mock: bool = False):
        self.gpu_limit = asyncio.Semaphore(10)
        self.use_mock = use_mock
        self.collection_name = Config.COLLECTION_NAME
        # 修改點：這裡名稱要跟下面一致
        self.client = None 

    async def _ensure_client(self):
        """確保 client 已掛載"""
        if self.client is None:
            target_host = str(Config.VECTOR_DB_HOST).strip()
            target_port = int(str(Config.VECTOR_DB_PORT).strip())
            
            logger.info(f"[Vector Repo] 正在連線至遠端 Qdrant: {target_host}:{target_port}")
            
            self.client = AsyncQdrantClient(
                host=target_host,
                port=target_port,
                timeout=10
            )
        return self.client

    

    async def search_in_ids(
        self, 
        query_vector: List[float],
        rdbms_ids: List[Any]
    ) -> List[VectorSearchResult]:
        """
        純語意特徵召回通道：動態放行全量 ID 範疇，防止特徵分數被 limit 截斷
        """
        self.client = await self._ensure_client()

        try:
            clean_ids = [int(i) for i in rdbms_ids if i is not None]
        except (ValueError, TypeError):
            return []
        if not clean_ids: return []

        search_filter = qmodels.Filter(
            must=[qmodels.FieldCondition(key="place_id", match=qmodels.MatchAny(any=clean_ids))]
        )

        # 🟢 關鍵修正：將 limit 動態調整為與 clean_ids 一致的長度
        dynamic_limit = len(clean_ids)

        try:
            logger.info(f"[Vector Repo] 執行純特徵空間投影，候選範疇: {dynamic_limit}")
            response = await self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=search_filter,
                limit=dynamic_limit,  # 👈 修正：不留任何死角，全量計算
                with_payload=True
            )
            results = response.points
        except AttributeError:
            results = await self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=search_filter,
                limit=dynamic_limit,  # 👈 修正：舊版 Search API 同步鬆綁
                with_payload=True
            )

        return [
            VectorSearchResult(
                id=res.payload.get("place_id"), 
                score=res.score,
                review_summary=res.payload.get("review_summary", "")
            ) 
            for res in results if res.payload
        ]


    async def get_dtos_by_ids(self, rdbms_ids: List[Any]) -> List[VectorSearchResult]:

        self.client = await self._ensure_client()
        
        clean_ids = [int(i) for i in rdbms_ids if i is not None]
        
        response, _ = await self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=qmodels.Filter(must=[
                qmodels.FieldCondition(key="place_id", match=qmodels.MatchAny(any=clean_ids))
            ]),
            with_payload=True, 
            limit=500  
        )
        
        # 直接回傳封裝好的 DTO，LLM 拿到的就是完整的上下文 (Context)
        return [VectorSearchResult(
            id=res.payload.get("place_id"),
            score=1.0, # 純排序模式下設為 1.0
            review_summary=res.payload.get("review_summary", "無評論摘要"),
            # 也可以把其他屬性一起補進去，讓 LLM 的 Prompt 更豐富
            cuisine_type=res.payload.get("cuisine_type", []),
            food_type=res.payload.get("food_type", []),
            flavor=res.payload.get("flavor", [])
        ) for res in response if res.payload]