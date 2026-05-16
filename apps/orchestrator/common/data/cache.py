"""
Redis 클라이언트 추상화.

LangGraph 체크포인터와 별개로, 애플리케이션 레벨의 캐싱(예: 세션 메타데이터,
결과 캐싱)에 사용할 수 있는 얇은 래퍼를 제공합니다.
redis_enabled=False 이면 NoopCache로 대체되어 아무 오류 없이 작동합니다.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class NoopCache:
    """Redis 비활성화 시 사용하는 아무 동작도 하지 않는 캐시."""

    async def get(self, key: str) -> Any:
        return None

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        pass

    async def delete(self, key: str) -> None:
        pass

    async def exists(self, key: str) -> bool:
        return False


class RedisCache:
    """aioredis 기반 비동기 Redis 캐시 클라이언트."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client = None

    async def _ensure_client(self):
        if self._client is None:
            import redis.asyncio as aioredis
            self._client = await aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def get(self, key: str) -> str | None:
        client = await self._ensure_client()
        try:
            return await client.get(key)
        except Exception as e:
            logger.warning("[RedisCache] get 실패: %s", e)
            return None

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        client = await self._ensure_client()
        try:
            await client.set(key, value, ex=ttl)
        except Exception as e:
            logger.warning("[RedisCache] set 실패: %s", e)

    async def delete(self, key: str) -> None:
        client = await self._ensure_client()
        try:
            await client.delete(key)
        except Exception as e:
            logger.warning("[RedisCache] delete 실패: %s", e)

    async def exists(self, key: str) -> bool:
        client = await self._ensure_client()
        try:
            return bool(await client.exists(key))
        except Exception as e:
            logger.warning("[RedisCache] exists 실패: %s", e)
            return False


_cache_instance: RedisCache | NoopCache | None = None


def get_cache() -> "RedisCache | NoopCache":
    """설정에 따라 Redis 또는 NoopCache 싱글턴을 반환합니다."""
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance

    from apps.orchestrator.common.config import get_settings
    s = get_settings()
    if s.redis_enabled:
        _cache_instance = RedisCache(s.redis_url)
        logger.info("[Cache] RedisCache 초기화: %s", s.redis_url)
    else:
        _cache_instance = NoopCache()
        logger.info("[Cache] NoopCache 사용 (redis_enabled=false)")
    return _cache_instance
