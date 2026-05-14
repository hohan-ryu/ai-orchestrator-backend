"""
Tier 2: 임베딩 기반 유사도 매칭.
LLM Gateway의 embed()를 통해 벡터화하고 스토어(Qdrant 또는 파일 캐시)와 비교합니다.
gateway_mode=mock 이면 API 호출 없이 키워드 기반 mock 임베딩을 사용합니다.
"""

import logging
from apps.orchestrator.config import Settings
from apps.orchestrator.llm_gateway import get_gateway
from apps.orchestrator.schemas.models import Intent

logger = logging.getLogger(__name__)


async def get_embedding(text: str, settings: Settings) -> list[float] | None:
    """텍스트를 임베딩 벡터로 변환합니다. 실패 시 None 반환."""
    return await get_gateway(settings).embed(text)


async def match_from_store(
    text: str,
    store,   # AsyncIntentCache | QdrantIntentStore (공통 async 인터페이스)
    settings: Settings,
) -> tuple[Intent, list[float], str] | tuple[None, list[float] | None, None]:
    """
    스토어에서 유사한 의도를 검색합니다.
    Returns:
        (intent, embedding, "cache") — 유사도 임계값 이상의 결과 발견
        (None, embedding, None)     — 미발견 (embedding은 Tier 3 이후 캐시 저장에 재사용)
        (None, None, None)          — 임베딩 생성 실패
    """
    embedding = await get_embedding(text, settings)
    if embedding is None:
        return None, None, None

    intent, score = await store.find_similar(embedding, settings.embedding_similarity_threshold)
    if intent is not None:
        return intent, embedding, "cache"

    return None, embedding, None
