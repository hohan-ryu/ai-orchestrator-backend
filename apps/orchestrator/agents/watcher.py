"""
watchdog 기반 에이전트 파일 감시.
agents/ 디렉토리의 변경을 감지해 AgentRegistry에 알립니다.
"""

import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_WATCHED_EXTENSIONS = {".yaml", ".yml", ".json", ".md"}


class AgentFileWatcher:
    def __init__(self, directory: Path, callback: Callable[[Path, str], None]) -> None:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        self._observer = Observer()

        class _Handler(FileSystemEventHandler):
            def __init__(self, cb: Callable[[Path, str], None]) -> None:
                self._cb = cb

            def _dispatch(self, path: str, event_type: str) -> None:
                p = Path(path)
                if p.suffix.lower() in _WATCHED_EXTENSIONS:
                    logger.info("[AgentWatcher] 파일 %s: %s", event_type, p.name)
                    self._cb(p, event_type)

            def on_created(self, event):
                if not event.is_directory:
                    self._dispatch(event.src_path, "created")

            def on_modified(self, event):
                if not event.is_directory:
                    self._dispatch(event.src_path, "modified")

            def on_deleted(self, event):
                if not event.is_directory:
                    self._dispatch(event.src_path, "deleted")

        self._observer.schedule(_Handler(callback), str(directory), recursive=False)

    def start(self) -> None:
        self._observer.start()
        logger.info("[AgentWatcher] 파일 감시 시작")

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        logger.info("[AgentWatcher] 파일 감시 종료")
