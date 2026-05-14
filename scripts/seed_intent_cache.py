"""
인텐트 캐시 시드 스크립트.
서버 최초 실행 전에 한 번 실행하면, 이후 유사 요청은 Tier 2(임베딩)에서 처리됩니다.

실행 방법:
  python -m scripts.seed_intent_cache
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.orchestrator.config import get_settings
from apps.orchestrator.intent.embedding_matcher import get_embedding
from apps.orchestrator.intent.cache import get_cache, _CACHE_FILE
from apps.orchestrator.schemas.models import Intent

SEED_EXAMPLES: list[dict] = [
    {
        "text": "github 레파지토리를 생성해줘",
        "intent": Intent(
            category="github_repo_create",
            summary="GitHub 레파지토리 생성 요청",
            entities={},
            confidence=0.95,
        ),
    },
    {
        "text": "github 레파지토리를 생성해주고 readme.md도 만들어줘",
        "intent": Intent(
            category="github_repo_create",
            summary="GitHub 레파지토리 및 README 생성 요청",
            entities={"extra_tasks": ["readme"]},
            confidence=0.90,
        ),
    },
    {
        "text": "python 프로젝트용 개발 환경을 구성해줘",
        "intent": Intent(
            category="dev_environment_setup",
            summary="개발 환경 구성 요청",
            entities={"language": "Python"},
            confidence=0.92,
        ),
    },
    {
        "text": "github actions ci/cd 파이프라인을 설정해줘",
        "intent": Intent(
            category="ci_cd_setup",
            summary="CI/CD 파이프라인 구성 요청",
            entities={},
            confidence=0.93,
        ),
    },
]


async def seed() -> None:
    settings = get_settings()
    cache = get_cache()

    print(f"캐시 파일 경로: {_CACHE_FILE}")
    print(f"현재 캐시 항목 수: {cache.size}")
    print()

    seeded = 0
    for example in SEED_EXAMPLES:
        text = example["text"]
        intent: Intent = example["intent"]

        print(f"임베딩 생성 중: '{text}'")
        embedding = await get_embedding(text, settings)
        if embedding is None:
            print(f"  ✗ 임베딩 실패 — 스킵")
            continue

        cache.add(text, embedding, intent)
        print(f"  ✓ 저장됨 → category={intent.category}, confidence={intent.confidence}")
        seeded += 1

    print()
    print(f"완료: {seeded}/{len(SEED_EXAMPLES)}건 시드 저장 (총 {cache.size}건)")


if __name__ == "__main__":
    asyncio.run(seed())
