"""
FastEmbed 기반 로컬 임베딩 어댑터 (ONNX Runtime, GPU 불필요).

지원 모델:
    - BAAI/bge-m3  (1024-dim, 다국어)
    - BAAI/bge-small-en-v1.5  (384-dim, 영어 경량)

첫 호출 시 모델이 자동 다운로드됩니다 (~570 MB for bge-m3).
FastEmbed은 동기 API이므로 asyncio.to_thread()로 이벤트 루프 블로킹을 방지합니다.
"""

import asyncio
import logging
from apps.orchestrator.llms.adapters.base import BaseAdapter, CompletionResponse

logger = logging.getLogger(__name__)


class LocalEmbeddingAdapter(BaseAdapter):
    def __init__(self, model_name: str = "BAAI/bge-m3") -> None:
        self._model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            logger.info("[LocalEmbed] 모델 로딩: %s", self._model_name)
            self._model = TextEmbedding(self._model_name)
            logger.info("[LocalEmbed] 모델 로딩 완료")
        return self._model

    async def embed(self, text: str, model: str) -> list[float] | None:
        def _run() -> list[float]:
            return list(self._load_model().embed([text]))[0].tolist()

        vector = await asyncio.to_thread(_run)
        logger.debug("[LocalEmbed] 완료 (dim=%d)", len(vector))
        return vector

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        raise NotImplementedError("LocalEmbeddingAdapter는 임베딩 전용입니다.")
