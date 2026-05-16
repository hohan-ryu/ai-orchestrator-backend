"""
에이전트 관리 REST API.

GET    /agents/            — 등록된 에이전트 목록
GET    /agents/{id}        — 에이전트 상세 정보 + 툴 목록
POST   /agents/            — 새 에이전트 생성 (YAML 파일 작성 + reload)
DELETE /agents/{id}        — 에이전트 삭제 (파일 제거 + reload)
POST   /agents/reload      — 전체 에이전트 hot-reload
POST   /agents/{id}/reload — 특정 에이전트 hot-reload
POST   /agents/{id}/ping   — 에이전트 연결 상태 확인
"""

import logging
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.orchestrator.agents.registry import get_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# 요청 스키마
# ---------------------------------------------------------------------------

class ToolCreateRequest(BaseModel):
    name: str
    description: str = ""


class APIConfigRequest(BaseModel):
    url: str
    timeout: int = 30
    auth_type: Literal["none", "bearer", "api_key", "basic"] = "none"
    auth_token: str = ""
    execute_path: str = "/execute"
    tools_path: str = "/tools"
    health_path: str = "/health"


class MCPConfigRequest(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout: int = 30


class AgentCreateRequest(BaseModel):
    id: str
    name: str
    type: Literal["file", "api", "mcp"]
    description: str = ""
    version: str = "1.0.0"
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
    tools: list[ToolCreateRequest] = Field(default_factory=list)
    system_prompt: str = ""          # file 타입용
    api: Optional[APIConfigRequest] = None   # api 타입용
    mcp: Optional[MCPConfigRequest] = None   # mcp 타입용


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _get_registry_or_404():
    registry = get_registry()
    if registry is None:
        raise HTTPException(status_code=503, detail="AgentRegistry가 초기화되지 않았습니다.")
    return registry


def _build_yaml(req: AgentCreateRequest) -> str:
    """AgentCreateRequest를 YAML 문자열로 직렬화합니다."""
    data: dict[str, Any] = {
        "id": req.id,
        "name": req.name,
        "type": req.type,
        "description": req.description,
        "version": req.version,
        "enabled": req.enabled,
    }
    if req.tags:
        data["tags"] = req.tags
    if req.tools:
        data["tools"] = [{"name": t.name, "description": t.description} for t in req.tools]
    if req.type == "api" and req.api:
        data["api"] = req.api.model_dump()
    if req.type == "mcp" and req.mcp:
        data["mcp"] = req.mcp.model_dump()
    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _write_agent_file(agents_dir: Path, req: AgentCreateRequest) -> Path:
    """에이전트 정의 파일을 agents/ 디렉토리에 씁니다."""
    if req.type == "file" and req.system_prompt:
        filename = f"{req.id}.agent.md"
        path = agents_dir / filename
        yaml_part = _build_yaml(req)
        content = f"---\n{yaml_part}---\n\n{req.system_prompt}\n"
        path.write_text(content, encoding="utf-8")
    else:
        filename = f"{req.id}.agent.yaml"
        path = agents_dir / filename
        path.write_text(_build_yaml(req), encoding="utf-8")
    return path


def _find_agent_file(agents_dir: Path, agent_id: str) -> Path | None:
    """agent_id에 해당하는 파일을 agents/ 디렉토리에서 찾습니다."""
    for ext in (".agent.yaml", ".agent.yml", ".agent.json", ".agent.md"):
        candidate = agents_dir / f"{agent_id}{ext}"
        if candidate.exists():
            return candidate
    # 확장자 패턴과 무관하게 파일명에 id가 포함된 경우도 검색
    for f in agents_dir.iterdir():
        if f.stem.split(".")[0] == agent_id or f.stem == agent_id:
            return f
    return None


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@router.get("/")
async def list_agents():
    """등록된 에이전트 전체 목록을 반환합니다."""
    registry = _get_registry_or_404()
    agents = registry.list_enabled()
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
            for m in agents
        ],
        "total": len(agents),
    }


@router.post("/")
async def create_agent(req: AgentCreateRequest):
    """새 에이전트를 생성합니다. agents/ 디렉토리에 파일을 작성하고 hot-reload합니다."""
    registry = _get_registry_or_404()

    if registry.get(req.id) is not None:
        raise HTTPException(status_code=409, detail=f"이미 존재하는 에이전트 ID입니다: '{req.id}'")

    agents_dir: Path = registry._dir
    path = _write_agent_file(agents_dir, req)
    count = await registry.reload_all()
    logger.info("[API] 에이전트 생성: %s → %s (전체 %d개)", req.id, path.name, count)
    return {"status": "ok", "agent_id": req.id, "file": path.name, "loaded": count}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """에이전트 파일을 삭제하고 레지스트리를 갱신합니다."""
    registry = _get_registry_or_404()

    if registry.get(agent_id) is None:
        raise HTTPException(status_code=404, detail=f"에이전트를 찾을 수 없습니다: '{agent_id}'")

    agents_dir: Path = registry._dir
    path = _find_agent_file(agents_dir, agent_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"에이전트 파일을 찾을 수 없습니다: '{agent_id}'")

    path.unlink()
    count = await registry.reload_all()
    logger.info("[API] 에이전트 삭제: %s (파일: %s, 전체 %d개)", agent_id, path.name, count)
    return {"status": "ok", "agent_id": agent_id, "loaded": count}


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
