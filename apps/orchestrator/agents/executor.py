"""
AgentExecutor — agent_id + tool 조합을 실행하는 단일 진입점.
registry에서 어댑터를 찾아 실행하고 결과를 반환합니다.
"""

import logging
from apps.orchestrator.agents.manifest import AgentResult
from apps.orchestrator.agents.registry import AgentRegistry

logger = logging.getLogger(__name__)


class AgentExecutor:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        agent_id: str,
        tool: str,
        input_data: dict,
        context: dict | None = None,
    ) -> AgentResult:
        adapter = self._registry.get_adapter(agent_id)
        if adapter is None:
            err = f"에이전트를 찾을 수 없습니다: '{agent_id}'"
            logger.error("[AgentExecutor] %s", err)
            return AgentResult(success=False, error=err, agent_id=agent_id, tool=tool)

        manifest = self._registry.get(agent_id)
        if manifest and not manifest.enabled:
            err = f"에이전트가 비활성화 상태입니다: '{agent_id}'"
            logger.warning("[AgentExecutor] %s", err)
            return AgentResult(success=False, error=err, agent_id=agent_id, tool=tool)

        logger.info("[AgentExecutor] 실행: %s.%s", agent_id, tool)
        result = await adapter.execute(tool, input_data, context)

        if result.success:
            logger.info("[AgentExecutor] 완료: %s.%s", agent_id, tool)
        else:
            logger.error("[AgentExecutor] 실패: %s.%s → %s", agent_id, tool, result.error)

        return result
