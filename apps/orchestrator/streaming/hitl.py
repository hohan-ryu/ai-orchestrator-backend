"""
HITL(Human-in-the-Loop) 세션 관리.

각 스트리밍 세션은 고유한 asyncio.Queue를 가집니다.
LangGraph interrupt 발생 시 SSE 스트림은 Queue에서 사용자 응답을 기다리고,
/resume 엔드포인트가 응답을 Queue에 push하면 그래프 실행이 재개됩니다.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class HITLManager:
    """세션별 HITL 응답 큐를 관리합니다."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}

    def register(self, session_id: str) -> asyncio.Queue:
        """새 세션을 등록하고 Queue를 반환합니다. SSE 스트림 시작 시 호출합니다."""
        q: asyncio.Queue = asyncio.Queue()
        self._queues[session_id] = q
        logger.debug("[HITL] 세션 등록: %s", session_id)
        return q

    async def send_response(self, session_id: str, response: str) -> bool:
        """사용자 응답을 해당 세션 Queue에 push합니다. 세션이 없으면 False 반환."""
        q = self._queues.get(session_id)
        if q is None:
            logger.warning("[HITL] 세션 없음: %s", session_id)
            return False
        await q.put(response)
        logger.debug("[HITL] 응답 전달: session=%s", session_id)
        return True

    def unregister(self, session_id: str) -> None:
        """스트리밍 종료 시 세션을 정리합니다."""
        self._queues.pop(session_id, None)
        logger.debug("[HITL] 세션 해제: %s", session_id)

    @property
    def active_sessions(self) -> list[str]:
        """현재 HITL 대기 중인 세션 ID 목록을 반환합니다."""
        return list(self._queues.keys())


# 애플리케이션 전역 싱글턴
hitl_manager = HITLManager()
