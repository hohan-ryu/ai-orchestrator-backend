"""
LLM/임베딩 어댑터의 추상 기반 클래스 및 공유 모델.
"""

from abc import ABC, abstractmethod
from pydantic import BaseModel


class CompletionResponse(BaseModel):
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str
    model: str
    from_mock: bool = False


class BaseAdapter(ABC):
    """모든 LLM/임베딩 어댑터의 공통 인터페이스."""

    @abstractmethod
    async def complete(self, model: str, system: str, user: str) -> CompletionResponse: ...

    @abstractmethod
    async def embed(self, text: str, model: str) -> list[float] | None: ...
