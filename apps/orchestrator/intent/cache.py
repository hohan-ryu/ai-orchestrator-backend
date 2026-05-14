"""
Tier 2: 임베딩 캐시.
과거에 분석한 의도를 임베딩 벡터와 함께 저장하고,
신규 요청이 들어오면 코사인 유사도로 가장 유사한 과거 의도를 찾아 반환합니다.
"""

import json
import logging
from pathlib import Path
import numpy as np
from apps.orchestrator.schemas.models import Intent

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent / "intent_cache.json"


class IntentCache:
    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        if _CACHE_FILE.exists():
            try:
                data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                self._entries = data.get("entries", [])
                logger.info("임베딩 캐시 로드: %d건", len(self._entries))
            except Exception as e:
                logger.warning("캐시 로드 실패, 초기화: %s", e)
                self._entries = []

    def save(self) -> None:
        try:
            _CACHE_FILE.write_text(
                json.dumps({"entries": self._entries}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("캐시 저장 실패: %s", e)

    def add(self, text: str, embedding: list[float], intent: Intent) -> None:
        self._entries.append({
            "text": text,
            "embedding": embedding,
            "intent": intent.model_dump(),
        })
        self.save()

    def find_similar(self, embedding: list[float], threshold: float = 0.92) -> tuple[Intent, float] | tuple[None, None]:
        """
        코사인 유사도로 가장 유사한 캐시 항목을 찾습니다.
        Returns: (Intent, score) if found above threshold, else (None, None)
        """
        if not self._entries:
            return None, None

        query = np.array(embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return None, None

        best_score = 0.0
        best_intent = None

        for entry in self._entries:
            cached = np.array(entry["embedding"], dtype=np.float32)
            cached_norm = np.linalg.norm(cached)
            if cached_norm == 0:
                continue
            score = float(np.dot(query, cached) / (query_norm * cached_norm))
            if score > best_score:
                best_score = score
                best_intent = entry["intent"]

        if best_score >= threshold and best_intent is not None:
            return Intent(**best_intent), best_score

        return None, None

    @property
    def size(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# 파일 기반 캐시 싱글턴
# ---------------------------------------------------------------------------

_cache_instance: IntentCache | None = None


def get_cache() -> IntentCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = IntentCache()
    return _cache_instance


# ---------------------------------------------------------------------------
# 비동기 래퍼 — IntentCache를 QdrantIntentStore와 동일한 인터페이스로 노출
# ---------------------------------------------------------------------------

class AsyncIntentCache:
    """파일 기반 IntentCache를 async 인터페이스로 감쌉니다."""

    def __init__(self, inner: IntentCache) -> None:
        self._inner = inner

    async def add(self, text: str, embedding: list[float], intent: Intent) -> None:
        self._inner.add(text, embedding, intent)

    async def find_similar(
        self, embedding: list[float], threshold: float
    ) -> tuple[Intent, float] | tuple[None, None]:
        return self._inner.find_similar(embedding, threshold)


# ---------------------------------------------------------------------------
# 스토어 팩토리 — 설정에 따라 Qdrant 또는 파일 기반 캐시를 반환
# ---------------------------------------------------------------------------

_store_instance = None


def get_intent_store(settings=None):
    """
    qdrant_enabled=True  → QdrantIntentStore (벡터 DB)
    qdrant_enabled=False → AsyncIntentCache  (로컬 JSON 파일)
    """
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    from apps.orchestrator.config import get_settings
    s = settings or get_settings()

    if s.qdrant_enabled:
        from apps.orchestrator.intent.qdrant_store import QdrantIntentStore
        _store_instance = QdrantIntentStore(
            url=s.qdrant_url,
            api_key=s.qdrant_api_key,
            collection=s.qdrant_collection,
            vector_size=s.qdrant_vector_size,
        )
        logger.info("인텐트 스토어: Qdrant (%s/%s)", s.qdrant_url, s.qdrant_collection)
    else:
        _store_instance = AsyncIntentCache(get_cache())
        logger.info("인텐트 스토어: 파일 기반 캐시 (%s)", _CACHE_FILE)

    return _store_instance


def reset_intent_store() -> None:
    """설정 변경 또는 테스트 시 스토어 인스턴스를 초기화합니다."""
    global _store_instance
    _store_instance = None
