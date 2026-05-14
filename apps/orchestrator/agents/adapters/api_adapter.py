"""
HTTP REST API 에이전트 어댑터.

에이전트 서버가 아래 두 엔드포인트를 구현해야 합니다:
  GET  {url}/tools     → [{"name": ..., "description": ..., "input_schema": {...}}, ...]
  POST {url}/execute   → {"tool": "...", "input": {...}, "context": {...}}
                       ← {"success": true, "output": "...", "data": {...}}
"""

import logging
import httpx
from apps.orchestrator.agents.manifest import AgentManifest, AgentTool, AgentResult
from apps.orchestrator.agents.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


class APIAdapter(BaseAdapter):
    def __init__(self, manifest: AgentManifest) -> None:
        super().__init__(manifest)
        cfg = manifest.api
        if cfg is None:
            raise ValueError(f"API 에이전트 [{manifest.id}]에 api 설정이 없습니다.")
        self._base_url = cfg.url.rstrip("/")
        self._timeout = cfg.timeout
        self._headers = self._build_headers(cfg)
        self._cfg = cfg

    def _build_headers(self, cfg) -> dict:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.auth_type == "bearer" and cfg.auth_token:
            headers["Authorization"] = f"Bearer {cfg.auth_token}"
        elif cfg.auth_type == "api_key" and cfg.auth_token:
            headers[cfg.auth_header] = cfg.auth_token
        elif cfg.auth_type == "basic" and cfg.auth_token:
            headers["Authorization"] = f"Basic {cfg.auth_token}"
        return headers

    async def execute(
        self,
        tool: str,
        input_data: dict,
        context: dict | None = None,
    ) -> AgentResult:
        payload = {"tool": tool, "input": input_data, "context": context or {}}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}{self._cfg.execute_path}",
                    json=payload,
                    headers=self._headers,
                )
                resp.raise_for_status()
                body = resp.json()
                return AgentResult(
                    success=body.get("success", True),
                    output=body.get("output", ""),
                    data=body.get("data", {}),
                    agent_id=self._manifest.id,
                    tool=tool,
                )
        except httpx.HTTPStatusError as e:
            err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error("[APIAdapter] %s.%s 오류: %s", self._manifest.id, tool, err)
            return AgentResult(success=False, error=err, agent_id=self._manifest.id, tool=tool)
        except Exception as e:
            logger.error("[APIAdapter] %s.%s 오류: %s", self._manifest.id, tool, e)
            return AgentResult(success=False, error=str(e), agent_id=self._manifest.id, tool=tool)

    async def list_tools(self) -> list[AgentTool]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}{self._cfg.tools_path}",
                    headers=self._headers,
                )
                resp.raise_for_status()
                return [AgentTool(**t) for t in resp.json()]
        except Exception as e:
            logger.warning("[APIAdapter] %s 툴 목록 조회 실패, 매니페스트 사용: %s", self._manifest.id, e)
            return self._manifest.tools

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{self._base_url}{self._cfg.health_path}",
                    headers=self._headers,
                )
                return resp.status_code < 400
        except Exception:
            return False
