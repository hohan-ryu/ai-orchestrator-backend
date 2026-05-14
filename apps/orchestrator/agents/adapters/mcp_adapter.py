"""
MCP (Model Context Protocol) 에이전트 어댑터.

에이전트를 stdio 기반 MCP 서버로 실행하고 도구를 호출합니다.
mcp 패키지가 필요합니다: pip install mcp
"""

import logging
from contextlib import AsyncExitStack
from apps.orchestrator.agents.manifest import AgentManifest, AgentTool, AgentResult
from apps.orchestrator.agents.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


class MCPAdapter(BaseAdapter):
    def __init__(self, manifest: AgentManifest) -> None:
        super().__init__(manifest)
        cfg = manifest.mcp
        if cfg is None:
            raise ValueError(f"MCP 에이전트 [{manifest.id}]에 mcp 설정이 없습니다.")
        self._cfg = cfg
        self._session = None
        self._exit_stack: AsyncExitStack | None = None

    async def _ensure_connected(self) -> None:
        if self._session is not None:
            return
        try:
            from mcp import ClientSession
            from mcp.client.stdio import stdio_client, StdioServerParameters
        except ImportError:
            raise RuntimeError(
                "MCP 어댑터를 사용하려면 mcp 패키지를 설치하세요: pip install mcp"
            )

        cfg = self._cfg
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env or None,
        )

        self._exit_stack = AsyncExitStack()
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        logger.info("[MCPAdapter] %s 연결 완료", self._manifest.id)

    async def execute(
        self,
        tool: str,
        input_data: dict,
        context: dict | None = None,
    ) -> AgentResult:
        try:
            await self._ensure_connected()
            result = await self._session.call_tool(tool, input_data)
            output = "\n".join(
                block.text for block in result.content if hasattr(block, "text")
            )
            return AgentResult(success=True, output=output, agent_id=self._manifest.id, tool=tool)
        except Exception as e:
            logger.error("[MCPAdapter] %s.%s 오류: %s", self._manifest.id, tool, e)
            # 연결 오류 가능성 → 세션 초기화해 다음 호출에서 재연결
            await self._reset_session()
            return AgentResult(success=False, error=str(e), agent_id=self._manifest.id, tool=tool)

    async def list_tools(self) -> list[AgentTool]:
        try:
            await self._ensure_connected()
            resp = await self._session.list_tools()
            return [
                AgentTool(
                    name=t.name,
                    description=t.description or "",
                    input_schema=dict(t.inputSchema) if t.inputSchema else {},
                )
                for t in resp.tools
            ]
        except Exception as e:
            logger.warning("[MCPAdapter] %s 툴 목록 조회 실패, 매니페스트 사용: %s", self._manifest.id, e)
            return self._manifest.tools

    async def ping(self) -> bool:
        try:
            await self._ensure_connected()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        await self._reset_session()

    async def _reset_session(self) -> None:
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
        self._session = None
        self._exit_stack = None
