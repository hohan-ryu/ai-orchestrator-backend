from abc import ABC, abstractmethod
from apps.orchestrator.agents.manifest import AgentManifest, AgentTool, AgentResult


class BaseAdapter(ABC):
    def __init__(self, manifest: AgentManifest) -> None:
        self._manifest = manifest

    @abstractmethod
    async def execute(
        self,
        tool: str,
        input_data: dict,
        context: dict | None = None,
    ) -> AgentResult: ...

    async def list_tools(self) -> list[AgentTool]:
        return self._manifest.tools

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass
