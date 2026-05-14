"""
LLM Gateway — 모든 LLM/임베딩 호출의 단일 진입점.

- 설정에 따라 프로바이더를 선택합니다 (google | anthropic | mock).
- 프로바이더 오류 시 fallback 체인(mock 포함)을 시도합니다.
- 호출마다 TokenTracker에 사용량을 기록합니다.
"""

import logging
from apps.orchestrator.config import Settings, get_settings
from apps.orchestrator.llm_gateway.models import CompletionResponse
from apps.orchestrator.llm_gateway.token_tracker import TokenTracker
from apps.orchestrator.llm_gateway.providers import (
    BaseProvider, GoogleProvider, AnthropicProvider, MockProvider, LocalEmbeddingProvider,
)

logger = logging.getLogger(__name__)


class LLMGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token_tracker = TokenTracker()
        self._providers: list[BaseProvider] = self._build_chain(settings)
        self._embed_provider: BaseProvider | None = self._build_embed_provider(settings)
        mode = "mock" if settings.gateway_mode == "mock" else f"{settings.llm_provider}→mock"
        embed_mode = settings.embedding_provider
        logger.info("[Gateway] 초기화 완료 (mode=%s, embed=%s)", mode, embed_mode)

    def _build_embed_provider(self, s: Settings) -> BaseProvider | None:
        """임베딩 전용 프로바이더 (LLM chain과 독립적으로 동작)."""
        if s.embedding_provider == "local":
            return LocalEmbeddingProvider(s.embedding_model_local)
        return None

    def _build_chain(self, s: Settings) -> list[BaseProvider]:
        """설정에 따라 프로바이더 fallback 체인을 구성합니다."""
        if s.gateway_mode == "mock":
            return [MockProvider()]

        chain: list[BaseProvider] = []
        if s.llm_provider == "google" and s.google_api_key:
            chain.append(GoogleProvider(s.google_api_key, s.llm_temperature))
        elif s.llm_provider == "anthropic" and s.anthropic_api_key:
            chain.append(AnthropicProvider(s.anthropic_api_key, s.llm_temperature))

        if s.gateway_fallback_to_mock:
            chain.append(MockProvider())

        if not chain:
            logger.warning("[Gateway] 유효한 프로바이더가 없어 Mock으로만 동작합니다.")
            chain.append(MockProvider())

        return chain

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        """텍스트 생성 호출. 프로바이더 오류 시 다음 fallback을 시도합니다."""
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                response = await provider.complete(model, system, user)
                self._token_tracker.record(
                    provider=response.provider,
                    model=response.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    call_type="complete",
                )
                if response.from_mock:
                    logger.info("[Gateway] Mock 응답 반환 (model=%s)", model)
                else:
                    logger.debug(
                        "[Gateway] %s 응답 완료 (in=%d out=%d)",
                        response.provider, response.input_tokens, response.output_tokens,
                    )
                return response
            except Exception as e:
                logger.warning("[Gateway] %s 실패: %s", provider.__class__.__name__, e)
                last_error = e

        raise RuntimeError(f"모든 프로바이더가 실패했습니다: {last_error}")

    async def embed(self, text: str) -> list[float] | None:
        """임베딩 벡터 생성.
        embedding_provider=local 이면 LocalEmbeddingProvider를 우선 사용하고,
        실패 시 LLM 프로바이더 체인으로 fallback합니다.
        """
        candidates: list[BaseProvider] = []
        if self._embed_provider is not None:
            candidates.append(self._embed_provider)
        candidates.extend(self._providers)

        for provider in candidates:
            model = (
                self._settings.embedding_model_local
                if isinstance(provider, LocalEmbeddingProvider)
                else self._settings.embedding_model
            )
            try:
                vector = await provider.embed(text, model)
                if vector is not None:
                    self._token_tracker.record(
                        provider=provider.__class__.__name__.lower().replace("provider", ""),
                        model=model,
                        input_tokens=len(text.split()),
                        output_tokens=0,
                        call_type="embed",
                    )
                    return vector
            except NotImplementedError:
                continue
            except Exception as e:
                logger.warning("[Gateway] Embed 실패 (%s): %s", provider.__class__.__name__, e)
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
    """설정 변경 또는 테스트 시 게이트웨이 인스턴스를 초기화합니다."""
    global _instance
    _instance = None
