"""
LLM Provider 관리 API.

Admin이 화면에서 LLM endpoint를 설정할 수 있는 CRUD API입니다.
소스코드 변경 없이 provider 추가/수정/삭제 및 즉시 반영이 가능합니다.

GET    /llm-providers/              — 전체 목록
GET    /llm-providers/{id}          — 상세 조회
POST   /llm-providers/              — 신규 등록
PUT    /llm-providers/{id}          — 수정
DELETE /llm-providers/{id}          — 삭제
POST   /llm-providers/{id}/enable   — 활성화
POST   /llm-providers/{id}/disable  — 비활성화
POST   /llm-providers/{id}/test     — 연결 테스트
POST   /llm-providers/reload        — 파일에서 강제 reload
GET    /llm-providers/adapters      — 지원 어댑터 목록
"""

import logging
from fastapi import APIRouter, HTTPException

from apps.orchestrator.llms.provider_config import (
    LLMProviderConfig, ProviderCreateRequest, ProviderUpdateRequest, ProviderResponse,
)
from apps.orchestrator.llms.provider_registry import get_provider_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/llm-providers", tags=["llm-providers"])

_SUPPORTED_ADAPTERS = [
    {"adapter": "google",    "description": "Google Gemini (LLM + Embedding)", "capability": ["completion", "embedding", "both"]},
    {"adapter": "anthropic", "description": "Anthropic Claude (LLM 전용)",     "capability": ["completion"]},
    {"adapter": "openai",    "description": "OpenAI GPT / 호환 API (base_url 변경 가능)", "capability": ["completion", "embedding", "both"]},
    {"adapter": "ollama",    "description": "Ollama 로컬 서버 (http://localhost:11434)", "capability": ["completion", "embedding", "both"]},
    {"adapter": "local",     "description": "FastEmbed 로컬 임베딩 (ONNX, GPU 불필요)", "capability": ["embedding"]},
    {"adapter": "mock",      "description": "테스트/폴백용 Mock (API 키 불필요)", "capability": ["completion", "embedding", "both"]},
]


def _get_registry_or_503():
    r = get_provider_registry()
    if r is None:
        raise HTTPException(status_code=503, detail="ProviderRegistry가 초기화되지 않았습니다.")
    return r


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

@router.get("/adapters")
async def list_adapters():
    """지원하는 어댑터 유형과 capability를 반환합니다."""
    return {"adapters": _SUPPORTED_ADAPTERS}


@router.get("/")
async def list_providers():
    """등록된 LLM provider 전체 목록을 반환합니다."""
    registry = _get_registry_or_503()
    providers = registry.list_all()
    return {
        "providers": [ProviderResponse.from_config(p) for p in providers],
        "total": len(providers),
        "enabled": sum(1 for p in providers if p.enabled),
    }


@router.get("/{provider_id}")
async def get_provider(provider_id: str):
    """특정 LLM provider 상세 정보를 반환합니다."""
    registry = _get_registry_or_503()
    cfg = registry.get(provider_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"provider 없음: '{provider_id}'")
    return ProviderResponse.from_config(cfg)


# ---------------------------------------------------------------------------
# 등록 / 수정 / 삭제
# ---------------------------------------------------------------------------

@router.post("/", status_code=201)
async def create_provider(body: ProviderCreateRequest):
    """새 LLM provider를 등록합니다. api_key는 서버에서 Fernet 암호화 후 저장됩니다."""
    registry = _get_registry_or_503()

    # api_key 암호화
    encrypted_key = registry.encrypt_api_key(body.api_key) if body.api_key else ""

    cfg = LLMProviderConfig(
        id=body.id,
        name=body.name or body.id,
        description=body.description,
        adapter=body.adapter,
        capability=body.capability,
        enabled=body.enabled,
        priority=body.priority,
        is_fallback=body.is_fallback,
        base_url=body.base_url,
        api_key=encrypted_key,
        model=body.model,
        embedding_model=body.embedding_model,
        temperature=body.temperature,
        timeout=body.timeout,
        max_retries=body.max_retries,
        tags=body.tags,
    )

    try:
        await registry.add(cfg)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info("[API] LLM provider 등록: %s (%s)", cfg.id, cfg.adapter)
    return {"status": "created", "provider": ProviderResponse.from_config(cfg)}


@router.put("/{provider_id}")
async def update_provider(provider_id: str, body: ProviderUpdateRequest):
    """provider 설정을 부분 업데이트합니다. api_key를 전달하면 재암호화합니다."""
    registry = _get_registry_or_503()

    updates = body.model_dump(exclude_none=True)

    # api_key가 포함된 경우 암호화
    if "api_key" in updates and updates["api_key"]:
        updates["api_key"] = registry.encrypt_api_key(updates["api_key"])

    try:
        updated = await registry.update(provider_id, updates)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 어댑터 캐시 무효화 (설정 변경 반영)
    from apps.orchestrator.llms.adapters.factory import invalidate
    invalidate(provider_id)

    logger.info("[API] LLM provider 업데이트: %s", provider_id)
    return {"status": "updated", "provider": ProviderResponse.from_config(updated)}


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str):
    """provider를 삭제합니다."""
    registry = _get_registry_or_503()
    try:
        await registry.remove(provider_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    from apps.orchestrator.llms.adapters.factory import invalidate
    invalidate(provider_id)

    logger.info("[API] LLM provider 삭제: %s", provider_id)
    return {"status": "deleted", "provider_id": provider_id}


# ---------------------------------------------------------------------------
# 활성화 / 비활성화
# ---------------------------------------------------------------------------

@router.post("/{provider_id}/enable")
async def enable_provider(provider_id: str):
    registry = _get_registry_or_503()
    try:
        await registry.update(provider_id, {"enabled": True})
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "enabled", "provider_id": provider_id}


@router.post("/{provider_id}/disable")
async def disable_provider(provider_id: str):
    registry = _get_registry_or_503()
    try:
        await registry.update(provider_id, {"enabled": False})
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "disabled", "provider_id": provider_id}


# ---------------------------------------------------------------------------
# 연결 테스트
# ---------------------------------------------------------------------------

@router.post("/{provider_id}/test")
async def test_provider(provider_id: str):
    """
    provider와 실제 연결을 테스트합니다.
    - completion 지원: 짧은 텍스트 생성 요청
    - embedding 지원: 짧은 텍스트 임베딩 요청
    """
    registry = _get_registry_or_503()
    cfg = registry.get(provider_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"provider 없음: '{provider_id}'")

    from apps.orchestrator.llms.adapters import factory

    resolved_key = registry.resolve_api_key(cfg.api_key)
    adapter = factory.create(cfg, resolved_key)
    results: dict = {"provider_id": provider_id, "adapter": cfg.adapter}

    if cfg.supports_completion():
        try:
            resp = await adapter.complete(
                cfg.model or "mock",
                "You are a test assistant. Reply with exactly: OK",
                "Test",
            )
            results["completion"] = {"ok": True, "model": resp.model, "provider": resp.provider}
        except Exception as e:
            results["completion"] = {"ok": False, "error": str(e)}

    if cfg.supports_embedding():
        try:
            vec = await adapter.embed("test", cfg.embedding_model or cfg.model or "mock")
            results["embedding"] = {"ok": vec is not None, "dim": len(vec) if vec else 0}
        except Exception as e:
            results["embedding"] = {"ok": False, "error": str(e)}

    overall_ok = all(v.get("ok", False) for v in results.values() if isinstance(v, dict))
    results["status"] = "ok" if overall_ok else "partial_failure"
    return results


# ---------------------------------------------------------------------------
# 강제 reload
# ---------------------------------------------------------------------------

@router.post("/reload")
async def reload_providers():
    """llm_providers.json을 다시 읽어 메모리를 갱신합니다."""
    registry = _get_registry_or_503()
    from apps.orchestrator.llms.adapters.factory import clear_cache
    clear_cache()
    count = await registry.reload()
    logger.info("[API] LLM provider reload — %d개", count)
    return {"status": "ok", "loaded": count}
