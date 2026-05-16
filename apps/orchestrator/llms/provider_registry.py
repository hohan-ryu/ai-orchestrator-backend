"""
LLM Provider Registry.

JSON 파일(llm_providers.json)에서 provider 목록을 로드하며,
Admin API를 통한 CRUD와 파일 변경 감지(watchdog) 기반 hot-reload를 지원합니다.

흐름:
  1. init_provider_registry(path)  — 앱 시작 시 lifespan에서 호출
  2. get_provider_registry()        — 어디서든 싱글턴 접근
  3. Admin API → save() 호출        — JSON 저장 및 in-memory 갱신
  4. watchdog FileModifiedEvent     — 외부에서 파일 편집 시 자동 reload
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Literal

from apps.orchestrator.llms.provider_config import LLMProviderConfig
from apps.orchestrator.common.encryption import encrypt, decrypt

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDERS: list[dict] = [
    {
        "id": "mock-fallback",
        "name": "Mock (기본 폴백)",
        "description": "API 키 없이 동작하는 테스트/폴백용 mock provider",
        "adapter": "mock",
        "capability": "both",
        "enabled": True,
        "priority": 99,
        "is_fallback": True,
        "model": "mock",
    }
]


def _resolve_api_key(raw: str) -> str:
    """
    ${ENV_VAR} 형식의 환경변수 참조를 실제 값으로 치환합니다.
    암호화된 값은 복호화합니다.
    """
    if not raw:
        return ""
    # 환경변수 참조
    match = re.fullmatch(r"\$\{([^}]+)\}", raw.strip())
    if match:
        return os.environ.get(match.group(1), "")
    # Fernet 복호화 시도
    return decrypt(raw)


class ProviderRegistry:
    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._providers: dict[str, LLMProviderConfig] = {}
        self._lock = asyncio.Lock()
        self._watcher = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # 로드 / 저장
    # ------------------------------------------------------------------

    def _load_sync(self) -> None:
        """파일에서 동기적으로 provider 목록을 로드합니다."""
        if not self._path.exists():
            logger.info("[ProviderRegistry] 설정 파일 없음 — 기본 mock provider 생성: %s", self._path)
            self._providers = {
                p["id"]: LLMProviderConfig(**p) for p in _DEFAULT_PROVIDERS
            }
            self._save_sync()
            return

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            loaded: dict[str, LLMProviderConfig] = {}
            for item in data.get("providers", []):
                try:
                    cfg = LLMProviderConfig(**item)
                    loaded[cfg.id] = cfg
                except Exception as e:
                    logger.warning("[ProviderRegistry] provider 파싱 오류 (id=%s): %s", item.get("id"), e)
            self._providers = loaded
            logger.info("[ProviderRegistry] 로드 완료 — %d개", len(self._providers))
        except Exception as e:
            logger.error("[ProviderRegistry] 파일 읽기 실패: %s", e)

    def _save_sync(self) -> None:
        """현재 메모리 상태를 JSON 파일로 저장합니다."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"providers": [p.model_dump() for p in self._providers.values()]}
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("[ProviderRegistry] 저장 완료: %s", self._path)
        except Exception as e:
            logger.error("[ProviderRegistry] 저장 실패: %s", e)

    async def reload(self) -> int:
        """파일을 다시 읽어 메모리를 갱신합니다."""
        async with self._lock:
            self._load_sync()
        return len(self._providers)

    async def save(self) -> None:
        """현재 메모리 상태를 파일로 저장합니다."""
        async with self._lock:
            self._save_sync()

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    def get(self, provider_id: str) -> LLMProviderConfig | None:
        return self._providers.get(provider_id)

    def list_all(self) -> list[LLMProviderConfig]:
        return list(self._providers.values())

    def list_enabled(
        self,
        capability: Literal["completion", "embedding", "both"] | None = None,
    ) -> list[LLMProviderConfig]:
        """
        활성화된 provider를 priority 오름차순으로 반환합니다.
        capability 필터: "completion"이면 completion/both 포함, "embedding"이면 embedding/both 포함.
        """
        result = [p for p in self._providers.values() if p.enabled]
        if capability == "completion":
            result = [p for p in result if p.supports_completion()]
        elif capability == "embedding":
            result = [p for p in result if p.supports_embedding()]
        return sorted(result, key=lambda p: (p.is_fallback, p.priority))

    # ------------------------------------------------------------------
    # 수정 (Admin API에서 호출)
    # ------------------------------------------------------------------

    async def add(self, config: LLMProviderConfig) -> None:
        """신규 provider를 추가합니다. api_key는 이미 암호화된 상태로 전달됩니다."""
        async with self._lock:
            if config.id in self._providers:
                raise ValueError(f"이미 존재하는 provider ID: '{config.id}'")
            self._providers[config.id] = config
            self._save_sync()
        logger.info("[ProviderRegistry] provider 추가: %s (%s)", config.id, config.adapter)

    async def update(self, provider_id: str, updates: dict) -> LLMProviderConfig:
        """provider 설정을 부분 업데이트합니다."""
        async with self._lock:
            existing = self._providers.get(provider_id)
            if existing is None:
                raise KeyError(f"provider 없음: '{provider_id}'")
            merged = {**existing.model_dump(), **{k: v for k, v in updates.items() if v is not None}}
            updated = LLMProviderConfig(**merged)
            self._providers[provider_id] = updated
            self._save_sync()
        logger.info("[ProviderRegistry] provider 업데이트: %s", provider_id)
        return updated

    async def remove(self, provider_id: str) -> None:
        async with self._lock:
            if provider_id not in self._providers:
                raise KeyError(f"provider 없음: '{provider_id}'")
            del self._providers[provider_id]
            self._save_sync()
        logger.info("[ProviderRegistry] provider 삭제: %s", provider_id)

    # ------------------------------------------------------------------
    # API 키 처리 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def encrypt_api_key(raw_key: str) -> str:
        """평문 API 키를 암호화합니다. ${ENV_VAR} 참조는 그대로 저장."""
        if not raw_key or re.fullmatch(r"\$\{[^}]+\}", raw_key.strip()):
            return raw_key
        return encrypt(raw_key)

    @staticmethod
    def resolve_api_key(stored_key: str) -> str:
        """저장된 API 키(암호화 or 환경변수 참조)를 실제 값으로 반환합니다."""
        return _resolve_api_key(stored_key)

    # ------------------------------------------------------------------
    # Watchdog hot-reload
    # ------------------------------------------------------------------

    def _start_watcher(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            registry_ref = self

            class _Handler(FileSystemEventHandler):
                def on_modified(self, event):
                    if Path(event.src_path).resolve() == registry_ref._path.resolve():
                        logger.info("[ProviderRegistry] 파일 변경 감지 — 자동 reload")
                        asyncio.run_coroutine_threadsafe(registry_ref.reload(), loop)

            observer = Observer()
            observer.schedule(_Handler(), str(self._path.parent), recursive=False)
            observer.start()
            self._watcher = observer
            logger.info("[ProviderRegistry] 파일 감시 시작: %s", self._path)
        except ImportError:
            logger.warning("[ProviderRegistry] watchdog 미설치 — 파일 hot-reload 비활성화")

    def stop_watcher(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher.join()
            self._watcher = None


# ---------------------------------------------------------------------------
# 싱글턴
# ---------------------------------------------------------------------------

_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry | None:
    return _registry


async def init_provider_registry(config_path: Path) -> ProviderRegistry:
    global _registry
    registry = ProviderRegistry(config_path)
    registry._load_sync()
    loop = asyncio.get_event_loop()
    registry._start_watcher(loop)
    _registry = registry
    return registry


async def shutdown_provider_registry() -> None:
    global _registry
    if _registry:
        _registry.stop_watcher()
        _registry = None
