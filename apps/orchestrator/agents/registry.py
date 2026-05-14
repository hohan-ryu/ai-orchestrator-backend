"""
AgentRegistry — 에이전트 싱글톤 레지스트리.

- agents/ 디렉토리의 .yaml / .yml / .json / .md 파일을 파싱해 에이전트를 등록합니다.
- watchdog으로 파일 변경을 감지하고 오케스트레이터 재시작 없이 hot-reload합니다.
- get_registry() / init_registry() 싱글톤 헬퍼로 어디서든 접근합니다.
"""

import asyncio
import json
import logging
import re
from pathlib import Path

import yaml

from apps.orchestrator.agents.manifest import AgentManifest, AgentTool
from apps.orchestrator.agents.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

_registry: "AgentRegistry | None" = None


# ---------------------------------------------------------------------------
# 파일 파싱 헬퍼
# ---------------------------------------------------------------------------

def _parse_md_frontmatter(path: Path) -> tuple[dict, str]:
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
    if match:
        frontmatter = yaml.safe_load(match.group(1)) or {}
        body = match.group(2).strip()
    else:
        frontmatter = {}
        body = content.strip()
    return frontmatter, body


def _parse_manifest(path: Path) -> AgentManifest | None:
    try:
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        elif suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        elif suffix == ".md":
            data, body = _parse_md_frontmatter(path)
            data["system_prompt"] = body
        else:
            return None

        if not data or "id" not in data:
            return None

        data["source_path"] = str(path)
        return AgentManifest.model_validate(data)
    except Exception as e:
        logger.error("[AgentRegistry] 파싱 오류 [%s]: %s", path.name, e)
        return None


def _build_adapter(manifest: AgentManifest) -> BaseAdapter:
    if manifest.type == "api":
        from apps.orchestrator.agents.adapters.api_adapter import APIAdapter
        return APIAdapter(manifest)
    if manifest.type == "mcp":
        from apps.orchestrator.agents.adapters.mcp_adapter import MCPAdapter
        return MCPAdapter(manifest)
    if manifest.type == "file":
        from apps.orchestrator.agents.adapters.file_adapter import FileAdapter
        return FileAdapter(manifest)
    raise ValueError(f"알 수 없는 에이전트 타입: {manifest.type}")


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------

class AgentRegistry:
    def __init__(self, agents_dir: Path) -> None:
        self._dir = agents_dir
        self._manifests: dict[str, AgentManifest] = {}
        self._adapters: dict[str, BaseAdapter] = {}
        self._watcher = None

    # ── 생명주기 ──

    async def start(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        await self._load_all()
        self._start_watcher()
        logger.info("[AgentRegistry] 시작 완료 — %d개 에이전트 등록", len(self._manifests))

    async def stop(self) -> None:
        self._stop_watcher()
        for adapter in list(self._adapters.values()):
            try:
                await adapter.close()
            except Exception as e:
                logger.warning("[AgentRegistry] 어댑터 종료 오류: %s", e)
        logger.info("[AgentRegistry] 종료")

    # ── 조회 ──

    def get(self, agent_id: str) -> AgentManifest | None:
        return self._manifests.get(agent_id)

    def list_enabled(self) -> list[AgentManifest]:
        return [m for m in self._manifests.values() if m.enabled]

    def get_adapter(self, agent_id: str) -> BaseAdapter | None:
        return self._adapters.get(agent_id)

    # ── 로드 / 언로드 ──

    async def reload_all(self) -> int:
        await self._load_all()
        return len(self._manifests)

    async def reload_one(self, agent_id: str) -> bool:
        m = self._manifests.get(agent_id)
        if m and m.source_path:
            await self._load_file(Path(m.source_path))
            return True
        return False

    async def _load_all(self) -> None:
        for path in sorted(self._dir.iterdir()):
            if path.suffix.lower() in {".yaml", ".yml", ".json", ".md"}:
                await self._load_file(path)

    async def _load_file(self, path: Path) -> None:
        manifest = _parse_manifest(path)
        if manifest is None:
            return

        # 기존 어댑터 교체
        old = self._adapters.pop(manifest.id, None)
        if old:
            await old.close()

        self._manifests[manifest.id] = manifest
        self._adapters[manifest.id] = _build_adapter(manifest)
        logger.info("[AgentRegistry] 로드: %s (%s) — %s", manifest.id, manifest.type, path.name)

    def _unload(self, agent_id: str) -> None:
        self._manifests.pop(agent_id, None)
        adapter = self._adapters.pop(agent_id, None)
        if adapter:
            asyncio.create_task(adapter.close())
        logger.info("[AgentRegistry] 제거: %s", agent_id)

    # ── 파일 감시 ──

    def _start_watcher(self) -> None:
        try:
            from apps.orchestrator.agents.watcher import AgentFileWatcher
            self._watcher = AgentFileWatcher(self._dir, self._on_file_event)
            self._watcher.start()
        except ImportError:
            logger.warning("[AgentRegistry] watchdog 미설치 → hot-reload 비활성화 (pip install watchdog)")

    def _stop_watcher(self) -> None:
        if self._watcher:
            self._watcher.stop()

    def _on_file_event(self, path: Path, event_type: str) -> None:
        """watchdog 스레드에서 호출 → asyncio 루프로 안전하게 전달."""
        try:
            loop = asyncio.get_event_loop()
            if event_type in ("created", "modified"):
                asyncio.run_coroutine_threadsafe(self._load_file(path), loop)
            elif event_type == "deleted":
                for agent_id, m in list(self._manifests.items()):
                    if m.source_path == str(path):
                        loop.call_soon_threadsafe(self._unload, agent_id)
        except Exception as e:
            logger.error("[AgentRegistry] 파일 이벤트 처리 오류: %s", e)


# ---------------------------------------------------------------------------
# 싱글톤 헬퍼
# ---------------------------------------------------------------------------

def get_registry() -> AgentRegistry | None:
    return _registry


async def init_registry(agents_dir: Path) -> AgentRegistry:
    global _registry
    _registry = AgentRegistry(agents_dir)
    await _registry.start()
    return _registry


async def shutdown_registry() -> None:
    global _registry
    if _registry:
        await _registry.stop()
        _registry = None
