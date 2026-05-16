"""
Ollama 어댑터 — 로컬 LLM 서버 (http://localhost:11434).

Ollama를 사용하면 인터넷 연결 없이 llama3, mistral, gemma 등
오픈소스 모델을 완전 로컬에서 실행할 수 있습니다.

설정:
    llm_provider = "ollama"
    ollama_base_url = "http://localhost:11434"   # 기본값

사전 준비:
    1. https://ollama.com 에서 Ollama 설치
    2. `ollama pull llama3` 로 원하는 모델 다운로드
    3. `ollama serve` 로 서버 시작 (또는 백그라운드 실행)
"""

import logging
from apps.orchestrator.llms.adapters.base import BaseAdapter, CompletionResponse

logger = logging.getLogger(__name__)


class OllamaAdapter(BaseAdapter):
    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self._base_url = base_url.rstrip("/")

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        import httpx

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        message = data.get("message", {})
        content = message.get("content", "")
        usage = data.get("usage", {})

        return CompletionResponse(
            content=content,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            provider="ollama",
            model=model,
        )

    async def embed(self, text: str, model: str) -> list[float] | None:
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("embedding")
