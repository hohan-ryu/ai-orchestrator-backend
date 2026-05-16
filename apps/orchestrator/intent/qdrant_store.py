"""
Qdrant 기반 의도 벡터 스토어.
임베딩 벡터를 Qdrant 컬렉션에 저장하고 코사인 유사도로 검색합니다.
qdrant_enabled=false 이면 이 모듈은 로드되지 않습니다.
"""

import uuid
import logging
from apps.orchestrator.common.schemas.models import Intent

logger = logging.getLogger(__name__)


class QdrantIntentStore:
    def __init__(
        self,
        url: str,
        api_key: str = "",
        collection: str = "intent_cache",
        vector_size: int = 768,
    ) -> None:
        from qdrant_client import AsyncQdrantClient
        self._client = AsyncQdrantClient(url=url, api_key=api_key or None)
        self._collection = collection
        self._vector_size = vector_size
        self._ready = False

    async def _ensure_collection(self) -> None:
        if self._ready:
            return
        from qdrant_client.models import Distance, VectorParams
        collections = await self._client.get_collections()
        existing = {c.name for c in collections.collections}
        if self._collection not in existing:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=self._vector_size, distance=Distance.COSINE
                ),
            )
            logger.info("[Qdrant] 컬렉션 생성: %s (dim=%d)", self._collection, self._vector_size)
        else:
            logger.debug("[Qdrant] 컬렉션 확인: %s", self._collection)
        self._ready = True

    async def add(self, text: str, embedding: list[float], intent: Intent) -> None:
        await self._ensure_collection()
        from qdrant_client.models import PointStruct
        # 동일 텍스트는 항상 같은 ID → upsert가 멱등적으로 동작
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, text))
        await self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(
                id=point_id,
                vector=embedding,
                payload={"text": text, "intent": intent.model_dump()},
            )],
        )
        logger.info("[Qdrant] 저장: '%s...' → %s", text[:40], intent.category)

    async def find_similar(
        self, embedding: list[float], threshold: float
    ) -> tuple[Intent, float] | tuple[None, None]:
        await self._ensure_collection()
        result = await self._client.query_points(
            collection_name=self._collection,
            query=embedding,
            limit=1,
            score_threshold=threshold,
        )
        points = result.points
        if not points:
            return None, None
        hit = points[0]
        intent = Intent(**hit.payload["intent"])
        logger.info("[Qdrant] 캐시 히트 (유사도=%.3f): %s", hit.score, intent.category)
        return intent, hit.score
