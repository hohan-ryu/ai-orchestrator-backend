"""
LLM / 임베딩 프로바이더 구현체.
  GoogleProvider   — Gemini (LLM + Embedding)
  AnthropicProvider — Claude (LLM only)
  MockProvider      — API 없이 동작하는 테스트용 프로바이더
"""

import asyncio
import json
import logging
import hashlib
from abc import ABC, abstractmethod

import numpy as np

from apps.orchestrator.llm_gateway.models import CompletionResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseProvider(ABC):
    @abstractmethod
    async def complete(self, model: str, system: str, user: str) -> CompletionResponse: ...

    @abstractmethod
    async def embed(self, text: str, model: str) -> list[float] | None: ...


# ---------------------------------------------------------------------------
# Google (Gemini)
# ---------------------------------------------------------------------------

class GoogleProvider(BaseProvider):
    def __init__(self, api_key: str, temperature: float = 0.0) -> None:
        self._api_key = api_key
        self._temperature = temperature

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=self._api_key,
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
            provider="google",
            model=model,
        )

    async def embed(self, text: str, model: str) -> list[float] | None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        embedder = GoogleGenerativeAIEmbeddings(
            model=model, google_api_key=self._api_key
        )
        return await embedder.aembed_query(text)


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------

class AnthropicProvider(BaseProvider):
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


# ---------------------------------------------------------------------------
# Mock — 키워드 기반 결정론적 임베딩 + 고정 JSON 응답
# ---------------------------------------------------------------------------

# 도메인 키워드 목록 (임베딩 유사도 계산에 사용)
_DOMAIN_KEYWORDS = [
    "github", "깃허브", "레파지토리", "레포", "repository", "repo",
    "개발", "환경", "dev", "environment", "docker", "venv", "virtualenv",
    "ci", "cd", "pipeline", "파이프라인", "자동", "배포", "actions",
    "프로젝트", "project", "scaffold", "boilerplate", "초기", "구조",
    "aws", "gcp", "azure", "terraform", "kubernetes", "k8s",
    "코드", "code", "함수", "function", "클래스", "class", "module",
    "readme", "문서", "license", "gitignore", "생성", "만들", "create",
    "setup", "설정", "구성", "추가", "python", "javascript", "typescript",
    "java", "go", "rust", "kotlin", "서버", "server",
]


def _mock_embedding(text: str, dim: int = 768) -> list[float]:
    """
    공통 키워드가 많은 텍스트일수록 코사인 유사도가 높아지는 결정론적 임베딩.
    동일 텍스트는 항상 동일 벡터를 반환합니다.
    """
    text_lower = text.lower()
    vec = np.zeros(dim, dtype=np.float32)

    for keyword in _DOMAIN_KEYWORDS:
        if keyword in text_lower:
            # 키워드마다 고정된 16개 차원에 가중치 부여
            h = int(hashlib.md5(keyword.encode()).hexdigest(), 16)
            for j in range(16):
                vec[(h + j * 137) % dim] += 1.0

    # 텍스트별 소량 노이즈 (동일 텍스트 → 동일 벡터 유지)
    text_seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2 ** 32)
    rng = np.random.RandomState(text_seed)
    vec += rng.normal(0, 0.05, dim).astype(np.float32)

    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.tolist()


def _detect_call_type(system: str) -> str:
    s = system.lower()
    if "의도" in s or "intent" in s or "category" in s or "confidence" in s:
        return "intent"
    if "계획" in s or "reasoning" in s or "tasks" in s:
        return "plan"
    if "종합" in s or "최종 답변" in s or "summary" in s:
        return "summary"
    return "execute"


def _infer_category(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["github", "깃허브", "레파지토리", "레포", "repo"]):
        return "github_repo_create"
    if any(k in t for k in ["ci", "cd", "파이프라인", "pipeline", "actions", "gitlab"]):
        return "ci_cd_setup"
    if any(k in t for k in ["docker", "개발 환경", "venv", "virtualenv"]):
        return "dev_environment_setup"
    if any(k in t for k in ["scaffold", "boilerplate", "프로젝트 구조", "초기 설정"]):
        return "project_scaffold"
    if any(k in t for k in ["aws", "gcp", "azure", "terraform", "kubernetes", "k8s"]):
        return "infra_provisioning"
    if any(k in t for k in ["코드", "함수", "클래스", "code", "function"]):
        return "code_generation"
    return "github_repo_create"


_MOCK_SUMMARIES = {
    "github_repo_create": "GitHub 레파지토리 생성 요청",
    "ci_cd_setup": "CI/CD 파이프라인 구성 요청",
    "dev_environment_setup": "개발 환경 구성 요청",
    "project_scaffold": "프로젝트 초기 구조 생성 요청",
    "infra_provisioning": "인프라 프로비저닝 요청",
    "code_generation": "코드 생성 요청",
}

_MOCK_PLANS = {
    "github_repo_create": {
        "reasoning": "[Mock] GitHub 레파지토리 생성을 위한 단계별 계획입니다.",
        "tasks": [
            {
                "title": "GitHub 레파지토리 생성",
                "description": "GitHub API를 호출하여 새 레파지토리를 생성합니다. (공개/비공개 설정 포함)",
            },
            {
                "title": "기본 파일 초기화",
                "description": "README.md, .gitignore, LICENSE 파일을 생성하고 초기 커밋을 수행합니다.",
            },
        ],
    },
    "dev_environment_setup": {
        "reasoning": "[Mock] 개발 환경 구성 단계별 계획입니다.",
        "tasks": [
            {"title": "의존성 설치", "description": "프로젝트에 필요한 패키지와 의존성을 설치합니다."},
            {"title": "환경 변수 설정", "description": ".env 파일과 환경 변수를 구성합니다."},
        ],
    },
    "ci_cd_setup": {
        "reasoning": "[Mock] CI/CD 파이프라인 구성 계획입니다.",
        "tasks": [
            {"title": "GitHub Actions 워크플로 생성", "description": ".github/workflows/ci.yml 파일을 생성합니다."},
            {"title": "배포 파이프라인 설정", "description": "자동 빌드 및 배포 단계를 구성합니다."},
        ],
    },
}


# ---------------------------------------------------------------------------
# Local (FastEmbed — ONNX 기반 로컬 임베딩, GPU 불필요)
# ---------------------------------------------------------------------------

class LocalEmbeddingProvider(BaseProvider):
    """
    FastEmbed 기반 로컬 임베딩 프로바이더.
    모델은 첫 embed() 호출 시 lazy 로딩됩니다 (~570 MB 다운로드).
    """

    def __init__(self, model_name: str = "BAAI/bge-m3") -> None:
        self._model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            logger.info("[Local] FastEmbed 모델 로딩 시작: %s", self._model_name)
            self._model = TextEmbedding(self._model_name)
            logger.info("[Local] FastEmbed 모델 로딩 완료")
        return self._model

    async def embed(self, text: str, model: str) -> list[float] | None:
        # FastEmbed은 동기 API → 스레드 풀에서 실행해 이벤트 루프 블로킹 방지
        def _run() -> list[float]:
            return list(self._load_model().embed([text]))[0].tolist()

        vector = await asyncio.to_thread(_run)
        logger.debug("[Local] 임베딩 완료 (dim=%d, model=%s)", len(vector), self._model_name)
        return vector

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        raise NotImplementedError("LocalEmbeddingProvider는 임베딩 전용입니다.")


class MockProvider(BaseProvider):
    """API 호출 없이 동작하는 테스트용 프로바이더."""

    async def complete(self, model: str, system: str, user: str) -> CompletionResponse:
        call_type = _detect_call_type(system)
        content = self._build_response(call_type, user)
        logger.debug("[Mock] call_type=%s", call_type)
        return CompletionResponse(
            content=content, provider="mock", model="mock", from_mock=True
        )

    async def embed(self, text: str, model: str) -> list[float] | None:
        logger.debug("[Mock] embed text=%r", text[:50])
        return _mock_embedding(text)

    def _build_response(self, call_type: str, user: str) -> str:
        if call_type == "intent":
            category = _infer_category(user)
            return json.dumps(
                {
                    "category": category,
                    "summary": _MOCK_SUMMARIES.get(category, "일반 요청"),
                    "entities": {},
                    "confidence": 0.90,
                },
                ensure_ascii=False,
            )
        if call_type == "plan":
            category = _infer_category(user)
            plan = _MOCK_PLANS.get(category, _MOCK_PLANS["github_repo_create"])
            return json.dumps(plan, ensure_ascii=False)
        if call_type == "summary":
            return f"[Mock] 모든 태스크가 완료되었습니다.\n\n요청 내용: {user[:300]}"
        # execute
        return "[Mock] 태스크를 성공적으로 완료했습니다."
