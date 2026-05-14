"""
Tier 1: Rule-based intent filter.
개발 환경 오케스트레이터 도메인에 특화된 키워드/정규식 규칙으로
LLM 호출 없이 명확한 요청을 즉시 분류합니다.
"""

import re
from apps.orchestrator.schemas.models import Intent

# (category, summary, confidence, patterns[])
_RULES: list[tuple[str, str, float, list[str]]] = [
    (
        "github_repo_create",
        "GitHub 레파지토리 생성 요청",
        0.95,
        [
            r"(github|깃허브|깃헙).{0,15}(레파지토리|레포지토리|레포|리포|repository|repo).{0,20}(생성|만들|create|추가|add)",
            r"(생성|만들|create).{0,20}(github|깃허브|깃헙).{0,15}(레파지토리|레포지토리|레포|리포|repository|repo)",
            r"new\s+(github\s+)?repo(sitory)?",
            r"init(ialize)?\s+(github\s+)?repo(sitory)?",
        ],
    ),
    (
        "dev_environment_setup",
        "개발 환경 구성 요청",
        0.92,
        [
            r"(개발|dev(elop(ment|er)?)?)\s*(환경|environment|env)\s*(구성|설정|생성|만들|create|setup|세팅|셋업)",
            r"(구성|설정|세팅|셋업)\s*(개발|dev)\s*(환경|environment|env)",
            r"(docker|도커)\s*(환경|컨테이너|container|compose)?\s*(구성|설정|생성|만들|create|setup|실행)",
            r"(virtualenv|venv|가상\s*환경|conda\s*env)\s*(생성|만들|create|setup)",
            r"(개발|dev).{0,10}(서버|server)\s*(설정|구성|세팅|setup)",
        ],
    ),
    (
        "ci_cd_setup",
        "CI/CD 파이프라인 구성 요청",
        0.93,
        [
            r"(ci|cd|ci[/_\-]?cd|cicd)\s*(파이프라인|pipeline)?\s*(구성|설정|생성|만들|create|setup|추가|add)",
            r"(github\s+actions?|깃허브\s+액션|gitlab\s+ci)\s*(구성|설정|생성|만들|create|setup|추가)",
            r"(자동|auto(matic)?)\s*(배포|deploy(ment)?|빌드|build)\s*(설정|구성|setup)",
        ],
    ),
    (
        "project_scaffold",
        "프로젝트 스캐폴딩/초기 구조 생성 요청",
        0.90,
        [
            r"(프로젝트|project)\s*(구조|structure|skeleton|scaffold|boilerplate|템플릿|template)\s*(생성|만들|create|setup)",
            r"(초기|initial|기본)\s*(프로젝트|project)\s*(설정|구성|생성|setup|create)",
            r"(monorepo|모노레포)\s*(구성|설정|생성|setup|create)",
        ],
    ),
    (
        "infra_provisioning",
        "인프라 프로비저닝 요청",
        0.90,
        [
            r"(aws|gcp|azure|cloud)\s*(리소스|resource|인프라|infra(structure)?)\s*(생성|프로비저닝|provisioning|setup|구성)",
            r"(terraform|pulumi|ansible)\s*(적용|apply|실행|run|설정|setup)",
            r"(kubernetes|k8s|쿠버네티스)\s*(클러스터|cluster|배포|deploy)\s*(설정|구성|생성)",
        ],
    ),
    (
        "code_generation",
        "코드 생성 요청",
        0.88,
        [
            r"(코드|code)\s*(작성|생성|만들|write|create|generate)",
            r"(함수|function|클래스|class|모듈|module)\s*(작성|생성|만들|write|create)",
            r"(구현|implement|개발|develop)\s*.{0,20}(코드|code|함수|function|클래스|class)",
        ],
    ),
]


_COMPOUND_PATTERNS = [
    # 동사 + 접속 조사/연결어 패턴: "생성해주고", "만들어주고", "만들고"
    r"(생성|만들|create|추가|설정|구성|setup|add).{0,8}(하고|해주고|고\s|고,)",
    # "도 생성", "도 만들" — 추가 작업 존재
    r"\S+\s*(도|도\s+)\s*(생성|만들|create|추가|설정)",
    # 명시적 열거/연결
    r"(그리고|그\s*다음|그\s*외에도|또한|and\s|,\s*(그리고|또))",
]


def _is_compound_request(text: str) -> bool:
    """복합 태스크(두 가지 이상 작업)가 포함된 요청인지 판단합니다."""
    return any(re.search(p, text, re.IGNORECASE) for p in _COMPOUND_PATTERNS)


def match_rules(text: str) -> tuple[Intent, str] | tuple[None, None]:
    """
    규칙 기반으로 의도를 분류합니다.
    복합 요청(하고, 그리고, ~도 생성 등)은 Tier 2/3로 넘깁니다.
    Returns: (Intent, "rule") if matched, else (None, None)
    """
    normalized = text.strip().lower()

    # 복합 요청이면 LLM/임베딩으로 넘김
    if _is_compound_request(normalized):
        return None, None

    for category, summary, confidence, patterns in _RULES:
        for pattern in patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                entities = _extract_entities(normalized, category)
                return (
                    Intent(
                        category=category,
                        summary=summary,
                        entities=entities,
                        confidence=confidence,
                    ),
                    "rule",
                )
    return None, None


def _extract_entities(text: str, category: str) -> dict:
    """카테고리별 기본 엔티티를 추출합니다."""
    entities: dict = {}

    # 프로그래밍 언어
    lang_map = {
        "python": "Python", "파이썬": "Python",
        "node": "Node.js", "nodejs": "Node.js",
        "java": "Java", "go": "Go", "golang": "Go",
        "typescript": "TypeScript", "ts": "TypeScript",
        "javascript": "JavaScript", "js": "JavaScript",
        "rust": "Rust", "kotlin": "Kotlin",
    }
    for key, val in lang_map.items():
        if key in text:
            entities["language"] = val
            break

    # 저장소 이름 힌트
    repo_match = re.search(r"['\"]([a-zA-Z0-9_\-]+)['\"]", text)
    if repo_match:
        entities["repo_name"] = repo_match.group(1)

    # 가시성
    if any(w in text for w in ["private", "프라이빗", "비공개"]):
        entities["visibility"] = "private"
    elif any(w in text for w in ["public", "퍼블릭", "공개"]):
        entities["visibility"] = "public"

    return entities
