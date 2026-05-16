"""
LLM Gateway — 모든 LLM/임베딩 호출의 단일 진입점.

ProviderRegistry에서 동적으로 어댑터 체인을 구성합니다.
Admin API로 provider를 추가/수정/삭제하면 소스코드 변경 없이 즉시 반영됩니다.

체인 실행 규칙:
  1. is_fallback=False 인 provider를 priority 오름차순으로 시도
  2. 전부 실패하면 is_fallback=True 인 provider를 시도
  3. 모두 실패하면 RuntimeError 발생

Registry 미초기화 시에는 Settings 기반 레거시 체인으로 자동 fallback합니다.
"""

import logging
from typing import Literal

from apps.orchestrator.common.config import Settings, get_settings
from apps.orchestrator.llms.adapters.base import BaseAdapter, CompletionResponse
from apps.orchestrator.llms.token_tracker import TokenTracker

logger = logging.getLogger(__name__)


def _build_legacy_chain(s: Settings) -> list[BaseAdapter]:
    """Registry 미초기화 시 Settings 기반으로 최소 체인을 구성합니다."""
    from apps.orchestrator.llms.adapters.mock.mock import MockAdapter
    from apps.orchestrator.llms.adapters.public.google import GoogleAdapter
    from apps.orchestrator.llms.adapters.public.anthropic import AnthropicAdapter
    from apps.orchestrator.llms.adapters.private.ollama import OllamaAdapter

    if s.gateway_mode == "mock":
        return [MockAdapter()]

    chain: list[BaseAdapter] = []
    if s.llm_provider == "google" and s.google_api_key:
        chain.append(GoogleAdapter(s.google_api_key, s.llm_temperature))
    elif s.llm_provider == "anthropic" and s.anthropic_api_key:
        chain.append(AnthropicAdapter(s.anthropic_api_key, s.llm_temperature))
    elif s.llm_provider == "ollama":
        chain.append(OllamaAdapter(getattr(s, "ollama_base_url", "http://localhost:11434")))

    if s.gateway_fallback_to_mock or not chain:
        chain.append(MockAdapter())
    return chain


def _build_legacy_embed_provider(s: Settings) -> BaseAdapter | None:
    if s.embedding_provider == "local":
        from apps.orchestrator.llms.adapters.embedding.local import LocalEmbeddingAdapter
        return LocalEmbeddingAdapter(s.embedding_model_local)
    return None


class LLMGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token_tracker = TokenTracker()
        logger.info("[Gateway] 초기화 완료 (ProviderRegistry 기반 동적 체인)")

    # ------------------------------------------------------------------
    # 체인 구성 — 매 호출마다 registry에서 fresh하게 읽음
    # ------------------------------------------------------------------

    def _get_chain(
        self,
        capability: Literal["completion", "embedding"],
    ) -> list[tuple[BaseAdapter, str]]:
        """
        (adapter, model) 튜플 목록을 반환합니다.
        registry가 초기화되어 있으면 registry를 사용하고, 아니면 settings 기반 레거시 chain을 반환합니다.
        """
        from apps.orchestrator.llms.provider_registry import get_provider_registry
        from apps.orchestrator.llms.adapters import factory

        registry = get_provider_registry()
        if registry is not None:
            providers = registry.list_enabled(capability)
            if providers:
                result = []
                for p in providers:
                    resolved_key = registry.resolve_api_key(p.api_key)
                    adapter = factory.create(p, resolved_key)
                    model = (
                        p.embedding_model or p.model
                        if capability == "embedding"
                        else p.model
                    )
                    result.append((adapter, model))
                return result

        # Registry 없음 → Settings 기반 레거시 체인
        logger.debug("[Gateway] registry 미초기화 — settings 기반 체인 사용")
        if capability == "completion":
            adapters = _build_legacy_chain(self._settings)
            model = self._settings.executor_model
            return [(a, model) for a in adapters]
        else:
            embed = _build_legacy_embed_provider(self._settings)
            adapters = ([embed] if embed else []) + _build_legacy_chain(self._settings)
            return [(a, self._settings.embedding_model_local if i == 0 and embed else self._settings.embedding_model)
                    for i, a in enumerate(adapters)]

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        """
        텍스트 생성. provider model 파라미터보다 config의 model이 우선됩니다.
        (호출자가 넘긴 model은 registry에 model이 없을 때 fallback으로 사용됩니다.)
        """
        chain = self._get_chain("completion")
        last_error: Exception | None = None

        for adapter, cfg_model in chain:
            effective_model = cfg_model or model
            try:
                response = await adapter.complete(effective_model, system, user)
                self._token_tracker.record(
                    provider=response.provider,
                    model=response.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    call_type="complete",
                )
                if response.from_mock:
                    logger.info("[Gateway] Mock 응답 (model=%s)", effective_model)
                else:
                    logger.debug(
                        "[Gateway] %s 완료 (in=%d out=%d)",
                        response.provider, response.input_tokens, response.output_tokens,
                    )
                return response
            except Exception as e:
                logger.warning("[Gateway] %s 실패: %s", adapter.__class__.__name__, e)
                last_error = e

        raise RuntimeError(f"모든 LLM provider가 실패했습니다: {last_error}")

    async def embed(self, text: str) -> list[float] | None:
        """임베딩 벡터 생성."""
        chain = self._get_chain("embedding")

        for adapter, model in chain:
            try:
                vector = await adapter.embed(text, model)
                if vector is not None:
                    self._token_tracker.record(
                        provider=adapter.__class__.__name__.lower().replace("adapter", ""),
                        model=model,
                        input_tokens=len(text.split()),
                        output_tokens=0,
                        call_type="embed",
                    )
                    return vector
            except NotImplementedError:
                continue
            except Exception as e:
                logger.warning("[Gateway] Embed 실패 (%s): %s", adapter.__class__.__name__, e)
        return None

    @property
    def token_tracker(self) -> TokenTracker:
        return self._token_tracker


# ---------------------------------------------------------------------------
# 애플리케이션 전역 싱글턴
# ---------------------------------------------------------------------------

_instance: LLMGateway | None = None


def get_gateway(settings: Settings | None = None) -> LLMGateway:
    global _instance
    if _instance is None:
        _instance = LLMGateway(settings or get_settings())
    return _instance


def reset_gateway() -> None:
    global _instance
    _instance = None
