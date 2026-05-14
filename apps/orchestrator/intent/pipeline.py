"""
3-tier 의도 분석 파이프라인.

Tier 1 (Rule)    → 비용 0,   즉시 반환
Tier 2 (Cache)   → 임베딩 1회, 스토어 유사도 검색 (Qdrant 또는 파일 캐시)
Tier 3 (LLM)     → LLM Gateway 호출, 결과를 스토어에 저장
"""

import logging
from apps.orchestrator.config import Settings
from apps.orchestrator.schemas.models import Intent
from apps.orchestrator.intent.rule_filter import match_rules
from apps.orchestrator.intent.embedding_matcher import match_from_store
from apps.orchestrator.intent.llm_analyzer import analyze_with_llm
from apps.orchestrator.intent.cache import get_intent_store

logger = logging.getLogger(__name__)


async def run_pipeline(
    text: str,
    settings: Settings,
    store=None,
) -> tuple[Intent, str]:
    """
    3-tier 파이프라인을 순서대로 실행합니다.

    Returns:
        (Intent, tier_used)  tier_used: "rule" | "cache" | "llm"
    """
    if store is None:
        store = get_intent_store(settings)

    # --- Tier 1: Rule-based ---
    intent, tier = match_rules(text)
    if intent is not None:
        logger.info("[Tier 1 Rule] 매칭: %s", intent.category)
        return intent, tier

    # --- Tier 2: 스토어 유사도 검색 ---
    intent, embedding, tier = await match_from_store(text, store, settings)
    if intent is not None:
        logger.info("[Tier 2 Cache] 히트: %s", intent.category)
        return intent, tier

    # --- Tier 3: LLM ---
    intent, tier = await analyze_with_llm(text, settings)
    logger.info("[Tier 3 LLM] 분석 완료: %s (신뢰도=%.2f)", intent.category, intent.confidence)

    # 신뢰도가 충분하면 스토어에 저장 → 다음 요청부터 Tier 2에서 활용
    if embedding is not None and intent.confidence >= 0.7:
        await store.add(text, embedding, intent)
        logger.info("[Tier 3 LLM] 스토어 저장 완료: %s", intent.category)

    return intent, tier
