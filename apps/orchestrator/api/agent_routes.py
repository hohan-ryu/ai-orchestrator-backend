"""
에이전트 관리 REST API.

GET    /agents/            — 등록된 에이전트 목록
GET    /agents/{id}        — 에이전트 상세 정보 + 툴 목록
POST   /agents/reload      — 전체 에이전트 hot-reload
POST   /agents/{id}/reload — 특정 에이전트 hot-reload
POST   /agents/{id}/ping   — 에이전트 연결 상태 확인
"""

import logging
from fastapi import APIRouter, HTTPException
from apps.orchestrator.agents.registry import get_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


def _get_registry_or_404():
    registry = get_registry()
    if registry is None:
        raise HTTPException(status_code=503, detail="AgentRegistry가 초기화되지 않았습니다.")
    return registry


@router.get("/")
async def list_agents():
    """등록된 에이전트 전체 목록을 반환합니다."""
    registry = _get_registry_or_404()
    return {
        "agents": [
            {
                "id": m.id,
                "name": m.name,
                "type": m.type,
                "description": m.description,
                "version": m.version,
                "enabled": m.enabled,
                "tags": m.tags,
                "tools": [{"name": t.name, "description": t.description} for t in m.tools],
            }
            for m in registry.list_enabled()
        ],
        "total": len(registry.list_enabled()),
    }


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """특정 에이전트의 상세 정보와 실시간 툴 목록을 반환합니다."""
    registry = _get_registry_or_404()
    manifest = registry.get(agent_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"에이전트를 찾을 수 없습니다: '{agent_id}'")

    adapter = registry.get_adapter(agent_id)
    tools = await adapter.list_tools() if adapter else manifest.tools

    return {
        "id": manifest.id,
        "name": manifest.name,
        "type": manifest.type,
        "description": manifest.description,
        "version": manifest.version,
        "enabled": manifest.enabled,
        "tags": manifest.tags,
        "source_path": manifest.source_path,
        "tools": [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ],
    }


@router.post("/reload")
async def reload_all_agents():
    """agents/ 디렉토리 전체를 다시 스캔해 에이전트를 재등록합니다."""
    registry = _get_registry_or_404()
    count = await registry.reload_all()
    logger.info("[API] 에이전트 전체 reload — %d개", count)
    return {"status": "ok", "loaded": count}


@router.post("/{agent_id}/reload")
async def reload_agent(agent_id: str):
    """특정 에이전트의 정의 파일을 다시 읽어 hot-reload합니다."""
    registry = _get_registry_or_404()
    ok = await registry.reload_one(agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"에이전트를 찾을 수 없습니다: '{agent_id}'")
    logger.info("[API] 에이전트 reload: %s", agent_id)
    return {"status": "ok", "agent_id": agent_id}


@router.post("/{agent_id}/ping")
async def ping_agent(agent_id: str):
    """에이전트 서버/프로세스 연결 상태를 확인합니다."""
    registry = _get_registry_or_404()
    adapter = registry.get_adapter(agent_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"에이전트를 찾을 수 없습니다: '{agent_id}'")
    alive = await adapter.ping()
    return {"agent_id": agent_id, "alive": alive}
