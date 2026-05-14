"""
File(agent.md) 에이전트 어댑터.

agent.md의 시스템 프롬프트를 LLM에 주입해 에이전트 역할을 수행합니다.
별도 서버 없이 동작하는 가장 간단한 에이전트 형태입니다.
"""

import logging
import json
from apps.orchestrator.agents.manifest import AgentManifest, AgentResult
from apps.orchestrator.agents.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


class FileAdapter(BaseAdapter):
    def __init__(self, manifest: AgentManifest) -> None:
        super().__init__(manifest)

    async def execute(
        self,
        tool: str,
        input_data: dict,
        context: dict | None = None,
    ) -> AgentResult:
        from apps.orchestrator.llm_gateway import get_gateway
        from apps.orchestrator.config import get_settings

        settings = get_settings()
        gateway = get_gateway(settings)

        system_prompt = self._manifest.system_prompt
        if not system_prompt:
            system_prompt = (
                f"당신은 {self._manifest.name}입니다.\n{self._manifest.description}"
            )

        tool_obj = next((t for t in self._manifest.tools if t.name == tool), None)
        tool_section = ""
        if tool_obj:
            tool_section = f"\n\n## 수행할 작업: {tool_obj.name}\n{tool_obj.description}"

        user_content = (
            f"{tool_section}\n\n"
            f"입력:\n{json.dumps(input_data, ensure_ascii=False, indent=2)}\n\n"
            f"컨텍스트:\n{json.dumps(context or {}, ensure_ascii=False, indent=2)}"
        )

        try:
            response = await gateway.complete(settings.executor_model, system_prompt, user_content)
            return AgentResult(
                success=True,
                output=response.content,
                agent_id=self._manifest.id,
                tool=tool,
            )
        except Exception as e:
            logger.error("[FileAdapter] %s.%s 오류: %s", self._manifest.id, tool, e)
            return AgentResult(success=False, error=str(e), agent_id=self._manifest.id, tool=tool)
