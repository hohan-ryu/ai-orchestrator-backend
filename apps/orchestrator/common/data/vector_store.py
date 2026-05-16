"""
Qdrant 기반 범용 벡터 스토어.

인텐트 도메인 지식 없이 순수 벡터 저장/검색만 담당합니다.
페이로드 구조(Intent 등)는 호출자가 결정합니다.
"""

import uuid
import logging
from typing import Any

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """
    Qdrant 컬렉션에 벡터와 임의 페이로드를 저장하고 유사도 검색을 수행합니다.

    Args:
        url: Qdrant 서버 URL
        collection: 컬렉션 이름
        vector_size: 벡터 차원 수
        api_key: Qdrant API 키 (없으면 인증 없음)
    """

    def __init__(
        self,
        url: str,
        collection: str,
        vector_size: int,
        api_key: str = "",
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
            logger.info("[VectorStore] 컬렉션 생성: %s (dim=%d)", self._collection, self._vector_size)
        else:
            # 기존 컬렉션 차원 확인 — 불일치 시 재생성
            info = await self._client.get_collection(self._collection)
            existing_size = info.config.params.vectors.size
            if existing_size != self._vector_size:
                logger.warning(
                    "[VectorStore] 차원 불일치 (기존=%d, 설정=%d) — 컬렉션 재생성",
                    existing_size, self._vector_size,
                )
                await self._client.delete_collection(self._collection)
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(
                        size=self._vector_size, distance=Distance.COSINE
                    ),
                )
        self._ready = True

    async def upsert(self, key: str, vector: list[float], payload: dict[str, Any]) -> None:
        """벡터와 페이로드를 저장합니다. 동일 key는 업서트(덮어쓰기)됩니다."""
        await self._ensure_collection()
        from qdrant_client.models import PointStruct
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
        await self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        logger.debug("[VectorStore] upsert: key=%r, id=%s", key[:40], point_id)

    async def search(
        self,
        vector: list[float],
        limit: int = 1,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        유사 벡터를 검색하여 페이로드 목록을 반환합니다.

        Returns:
            [{"payload": {...}, "score": float}, ...]
        """
        await self._ensure_collection()
        result = await self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=limit,
            score_threshold=score_threshold,
        )
        return [{"payload": p.payload, "score": p.score} for p in result.points]
