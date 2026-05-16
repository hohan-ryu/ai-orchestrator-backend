"""
어댑터 팩토리 — LLMProviderConfig로부터 어댑터 인스턴스를 생성하고 캐싱합니다.

동일한 config(config_hash 동일)에 대해서는 기존 인스턴스를 재사용합니다.
config가 변경되면 자동으로 새 인스턴스를 생성합니다.
(LocalEmbeddingAdapter 같이 모델을 메모리에 올리는 경우 불필요한 재로딩을 방지합니다.)
"""

import logging
from apps.orchestrator.llms.adapters.base import BaseAdapter
from apps.orchestrator.llms.provider_config import LLMProviderConfig

logger = logging.getLogger(__name__)

# {provider_id: (config_hash, adapter_instance)}
_cache: dict[str, tuple[str, BaseAdapter]] = {}


def create(config: LLMProviderConfig, resolved_key: str = "") -> BaseAdapter:
    """
    LLMProviderConfig로부터 어댑터 인스턴스를 반환합니다.

    Args:
        config:       provider 설정
        resolved_key: 이미 복호화된 API 키 (미전달 시 config.api_key 그대로 사용)
    """
    cfg_hash = config.config_hash()

    # 캐시 히트 — 동일 설정이면 기존 인스턴스 재사용
    cached = _cache.get(config.id)
    if cached is not None and cached[0] == cfg_hash:
        return cached[1]

    # 새 인스턴스 생성
    api_key = resolved_key or config.api_key
    adapter = _instantiate(config, api_key)
    _cache[config.id] = (cfg_hash, adapter)
    logger.info("[AdapterFactory] 어댑터 생성: %s (%s)", config.id, config.adapter)
    return adapter


def _instantiate(config: LLMProviderConfig, api_key: str) -> BaseAdapter:
    match config.adapter:
        case "google":
            from apps.orchestrator.llms.adapters.public.google import GoogleAdapter
            return GoogleAdapter(api_key=api_key, temperature=config.temperature)

        case "anthropic":
            from apps.orchestrator.llms.adapters.public.anthropic import AnthropicAdapter
            return AnthropicAdapter(api_key=api_key, temperature=config.temperature)

        case "openai":
            from apps.orchestrator.llms.adapters.public.openai import OpenAIAdapter
            return OpenAIAdapter(
                api_key=api_key,
                base_url=config.base_url or None,
                temperature=config.temperature,
            )

        case "ollama":
            from apps.orchestrator.llms.adapters.private.ollama import OllamaAdapter
            return OllamaAdapter(
                base_url=config.base_url or "http://localhost:11434",
                timeout=config.timeout,
            )

        case "local":
            from apps.orchestrator.llms.adapters.embedding.local import LocalEmbeddingAdapter
            return LocalEmbeddingAdapter(
                model_name=config.model or "BAAI/bge-m3"
            )

        case "mock":
            from apps.orchestrator.llms.adapters.mock.mock import MockAdapter
            return MockAdapter()

        case _:
            raise ValueError(f"지원하지 않는 어댑터 유형: '{config.adapter}'")


def invalidate(provider_id: str) -> None:
    """특정 provider의 캐시를 삭제합니다."""
    _cache.pop(provider_id, None)


def clear_cache() -> None:
    """전체 캐시를 삭제합니다."""
    _cache.clear()
