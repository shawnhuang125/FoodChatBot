from typing import List, Any, Optional
from app.models.search_dto import VectorSearchResult
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from app.config import Config
from app.utils.app_logger import logger
import asyncio


class VectorRepository:
    def __init__(self, use_mock: bool = False):
        self.gpu_limit = asyncio.Semaphore(10)
        self.use_mock = use_mock
        self.collection_name = Config.COLLECTION_NAME
        self.client: Optional[AsyncQdrantClient] = None

    async def _ensure_client(self) -> AsyncQdrantClient:
        """確保 client 已掛載"""
        if self.client is None:
            target_host = str(Config.VECTOR_DB_HOST).strip()
            target_port = int(str(Config.VECTOR_DB_PORT).strip())

            logger.info(f"[Vector Repo] 正在連線至遠端 Qdrant: {target_host}:{target_port}")

            self.client = AsyncQdrantClient(
                host=Config.VECTOR_DB_HOST,
                port=Config.VECTOR_DB_PORT,
                timeout=30.0
            )
        return self.client

    async def search_in_ids(
        self, 
        query_vector: List[float],
        rdbms_ids: List[Any],
        vector_name: Optional[str] = None
    ) -> List[VectorSearchResult]:
        """
        語意特徵召回通道：動態放行全量 ID 範疇
        - 當 vector_name 為 None 時，走預設單一向量空間（single 模式）
        - 當 vector_name 有指定值時，走指定命名向量空間（named 模式）
        """
        client = await self._ensure_client()

        try:
            clean_ids = [int(i) for i in rdbms_ids if i is not None]
        except (ValueError, TypeError):
            return []
        if not clean_ids:
            return []

        search_filter = qmodels.Filter(
            must=[qmodels.FieldCondition(key="place_id", match=qmodels.MatchAny(any=clean_ids))]
        )

        dynamic_limit = len(clean_ids)

        # 動態組裝 query 參數，無 vector_name 則不傳 using
        query_kwargs = {
            "collection_name": self.collection_name,
            "query": query_vector,
            "query_filter": search_filter,
            "limit": dynamic_limit,
            "with_payload": True
        }
        if vector_name:
            query_kwargs["using"] = vector_name

        try:
            logger.info(
                f"[Vector Repo] 執行特徵空間投影，目標通道: {'[預設單向量]' if not vector_name else vector_name}，候選範疇: {dynamic_limit}"
            )
            response = await client.query_points(**query_kwargs)
            results = response.points
        except AttributeError:
            # 舊版 SDK fallback
            legacy_kwargs = {
                "collection_name": self.collection_name,
                "query_vector": query_vector,
                "query_filter": search_filter,
                "limit": dynamic_limit,
                "with_payload": True
            }
            if vector_name:
                legacy_kwargs["using"] = vector_name
            results = await client.search(**legacy_kwargs)

        return [
            VectorSearchResult(
                id=res.payload.get("place_id"), 
                score=res.score,
                review_summary=res.payload.get("review_summary", ""),
                service_tags=res.payload.get("service_tags", [])
            ) 
            for res in results if res.payload
        ]

    async def get_dtos_by_ids(self, rdbms_ids: List[Any]) -> List[VectorSearchResult]:
        client = await self._ensure_client()

        clean_ids = [int(i) for i in rdbms_ids if i is not None]
        if not clean_ids:
            return []

        dynamic_limit = len(clean_ids)

        response, _ = await client.scroll(
            collection_name=self.collection_name,
            scroll_filter=qmodels.Filter(must=[
                qmodels.FieldCondition(key="place_id", match=qmodels.MatchAny(any=clean_ids))
            ]),
            with_payload=True,
            limit=dynamic_limit
        )

        return [
            VectorSearchResult(
                id=res.payload.get("place_id"),
                score=1.0,
                review_summary=res.payload.get("review_summary", "無評論摘要"),
                cuisine_type=res.payload.get("cuisine_type", []),
                food_type=res.payload.get("food_type", []),
                flavor=res.payload.get("flavor", []),
                facility_tags=res.payload.get("facility_tags", []),
                service_tags=res.payload.get("service_tags", [])
            )
            for res in response if res.payload
        ]