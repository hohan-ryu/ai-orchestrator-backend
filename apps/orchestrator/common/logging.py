"""
구조화 로깅 유틸리티.

모든 모듈에서 공통으로 사용할 수 있는 로거 팩토리와 컨텍스트 바인딩 헬퍼를 제공합니다.

사용법:
    from apps.orchestrator.common.logging import get_logger

    logger = get_logger(__name__)
    logger.info("처리 시작", extra={"session_id": sid, "tier": "llm"})
"""

import logging
import json
from typing import Any


class JsonFormatter(logging.Formatter):
    """JSON Lines 포맷 로그 포매터."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # extra 필드 병합 (logging 내부 키 제외)
        _skip = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "id", "levelname", "levelno", "lineno", "module",
            "msecs", "message", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "thread", "threadName",
        }
        for k, v in record.__dict__.items():
            if k not in _skip:
                payload[k] = v
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """이름으로 로거를 반환합니다 (표준 logging.getLogger 래퍼)."""
    return logging.getLogger(name)


def bind(logger: logging.Logger, **ctx) -> logging.LoggerAdapter:
    """컨텍스트 필드를 항상 extra로 첨부하는 LoggerAdapter를 반환합니다."""
    return logging.LoggerAdapter(logger, ctx)
