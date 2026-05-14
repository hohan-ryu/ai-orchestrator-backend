"""
Tier 3: LLM 기반 의도 분석.
Rule/캐시로 처리되지 않은 신규 요청에만 호출됩니다.
"""

import logging
from apps.orchestrator.config import Settings
from apps.orchestrator.llm_gateway import get_gateway
from apps.orchestrator.core.utils import safe_parse_json
from apps.orchestrator.schemas.models import Intent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 개발 환경 오케스트레이터 시스템의 의도 분석 전문가입니다.
사용자 요청에서 의도를 정확히 파악하여 아래 JSON 형식으로만 응답하세요.

지원하는 카테고리:
- github_repo_create: GitHub 레파지토리 생성
- dev_environment_setup: 개발 환경 구성 (Docker, venv, 서버 설정 등)
- ci_cd_setup: CI/CD 파이프라인 구성
- project_scaffold: 프로젝트 초기 구조 생성
- infra_provisioning: 클라우드/인프라 프로비저닝
- code_generation: 코드 작성/생성
- question_answering: 질문/설명 요청
- other: 위 카테고리에 해당하지 않는 요청

응답 형식:
{
  "category": "위 카테고리 중 하나",
  "summary": "의도를 한 문장으로 요약",
  "entities": {"핵심 엔티티 키": "값"},
  "confidence": 0.0 ~ 1.0
}

JSON 외 다른 텍스트는 포함하지 마세요."""

_FALLBACK_INTENT = Intent(
    category="other",
    summary="의도 분석에 실패하여 일반 요청으로 처리합니다.",
    entities={},
    confidence=0.0,
)


async def analyze_with_llm(text: str, settings: Settings) -> tuple[Intent, str]:
    """
    LLM Gateway를 통해 의도를 분석합니다.
    Returns: (Intent, "llm")
    """
    gateway = get_gateway(settings)

    try:
        response = await gateway.complete(settings.intent_model, _SYSTEM_PROMPT, text)
        parsed = safe_parse_json(response.content)
        intent = Intent(**parsed)
        logger.info(
            "LLM 의도 분석 완료: %s (신뢰도 %.2f, mock=%s)",
            intent.category, intent.confidence, response.from_mock,
        )
        return intent, "llm"
    except Exception as e:
        logger.warning("LLM 의도 분석 실패, fallback 사용: %s", e)
        return _FALLBACK_INTENT, "llm"
