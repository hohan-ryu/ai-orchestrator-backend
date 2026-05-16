"""
OpenAI 어댑터 (GPT 계열 + 임베딩).

base_url을 지정하면 OpenAI 호환 API (Azure OpenAI, LM Studio, vLLM 등)에도 사용할 수 있습니다.

설정 예시:
    adapter: openai
    api_key: sk-...
    model: gpt-4o
    base_url: ""                               # 기본 OpenAI API
    # 또는
    base_url: https://my-azure.openai.azure.com  # Azure OpenAI
"""

import logging
from apps.orchestrator.llms.adapters.base import BaseAdapter, CompletionResponse

logger = logging.getLogger(__name__)


class OpenAIAdapter(BaseAdapter):
    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._temperature = temperature

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        kwargs = dict(
            model=model,
            api_key=self._api_key,
            temperature=self._temperature,
        )
        if self._base_url:
            kwargs["base_url"] = self._base_url

        llm = ChatOpenAI(**kwargs)
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
            provider="openai",
            model=model,
        )

    async def embed(self, text: str, model: str) -> list[float] | None:
        from langchain_openai import OpenAIEmbeddings

        kwargs = dict(model=model, api_key=self._api_key)
        if self._base_url:
            kwargs["base_url"] = self._base_url

        embedder = OpenAIEmbeddings(**kwargs)
        return await embedder.aembed_query(text)
