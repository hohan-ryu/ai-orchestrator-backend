"""
Anthropic Claude 어댑터 (LLM 전용, 임베딩 미지원).
"""

import logging
from apps.orchestrator.llms.adapters.base import BaseAdapter, CompletionResponse

logger = logging.getLogger(__name__)


class AnthropicAdapter(BaseAdapter):
    def __init__(self, api_key: str, temperature: float = 0.0) -> None:
        self._api_key = api_key
        self._temperature = temperature

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatAnthropic(
            model=model,
            anthropic_api_key=self._api_key,
            temperature=self._temperature,
        )
        response = await llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        usage = getattr(response, "usage_metadata", None) or {}
        if not isinstance(usage, dict):
            usage = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            }
        return CompletionResponse(
            content=str(response.content),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            provider="anthropic",
            model=model,
        )

    async def embed(self, text: str, model: str) -> list[float] | None:
        return None  # Anthropic은 임베딩 API 미제공
