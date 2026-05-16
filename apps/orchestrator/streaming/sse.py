"""
SSE(Server-Sent Events) 스트리밍 핵심 로직.

LangGraph 그래프 실행 결과를 SSE 형식으로 변환하고,
HITL interrupt가 발생하면 HITLManager를 통해 사용자 응답을 기다립니다.

이벤트 흐름:
  1. 그래프 astream() → node 출력의 stream_events 를 SSE로 전송
  2. __interrupt__ chunk 감지 → HUMAN_INPUT_REQUIRED 이벤트 전송 + Queue 대기
  3. /resume 엔드포인트가 Queue에 push → HUMAN_INPUT_RECEIVED 이벤트 전송 → 그래프 재개
  4. 그래프 완료 → done 이벤트 전송
"""

import asyncio
import hashlib
import json
import logging
from typing import AsyncGenerator

from langgraph.types import Command

from apps.orchestrator.common.schemas.models import (
    OrchestrateRequest, StreamEvent, StreamEventType,
)
from apps.orchestrator.core.graph import get_graph
from apps.orchestrator.streaming.hitl import hitl_manager

logger = logging.getLogger(__name__)

_HITL_TIMEOUT_SECONDS = 600  # 10분


def make_initial_state(request: OrchestrateRequest, session_id: str) -> dict:
    """LangGraph 초기 상태를 생성합니다."""
    return {
        "user_input": request.message,
        "session_id": session_id,
        "intent": None,
        "intent_tier": None,
        "plan": None,
        "completed_tasks": [],
        "final_answer": "",
        "stream_events": [],
        "error": None,
    }


def _sse(event: StreamEvent) -> str:
    """StreamEvent를 SSE 포맷 문자열로 변환합니다."""
    return f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"


def _sse_raw(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_graph(
    request: OrchestrateRequest,
    session_id: str,
    hitl_queue: asyncio.Queue,
) -> AsyncGenerator[str, None]:
    """
    LangGraph 실행 결과를 SSE 형식으로 스트리밍하는 비동기 제너레이터.

    - 노드 출력의 stream_events를 SSE로 yield합니다.
    - HITL interrupt 발생 시 사용자 입력을 기다린 후 그래프를 재개합니다.
    - 동일 이벤트가 HITL 재실행으로 중복 전송되지 않도록 content hash로 필터링합니다.
    """
    config = {"configurable": {"thread_id": session_id}}
    current_input = make_initial_state(request, session_id)
    seen_event_ids: set[str] = set()

    try:
        while True:
            async for chunk in get_graph().astream(current_input, config, stream_mode="updates"):
                # ── HITL interrupt 감지 ──────────────────────────────────
                if "__interrupt__" in chunk:
                    for interrupt_obj in chunk["__interrupt__"]:
                        event = StreamEvent(
                            event=StreamEventType.HUMAN_INPUT_REQUIRED,
                            data=interrupt_obj.value if isinstance(interrupt_obj.value, dict) else {},
                            session_id=session_id,
                        )
                        yield _sse(event)
                        await asyncio.sleep(0)
                    continue

                # ── 일반 노드 출력 → stream_events 추출 ─────────────────
                for node_output in chunk.values():
                    if not isinstance(node_output, dict):
                        continue
                    for event in node_output.get("stream_events", []):
                        # content hash로 HITL 재실행 시 중복 이벤트 방지
                        serialized = json.dumps(
                            event.model_dump(), ensure_ascii=False, sort_keys=True
                        )
                        event_key = hashlib.md5(serialized.encode()).hexdigest()
                        if event_key in seen_event_ids:
                            continue
                        seen_event_ids.add(event_key)
                        yield f"data: {serialized}\n\n"
                        await asyncio.sleep(0)

            # ── 그래프 상태 확인: interrupt 중이면 사용자 응답 대기 ──────
            graph_state = await get_graph().aget_state(config)
            if not graph_state.next:
                break  # 그래프 정상 완료

            try:
                user_response = await asyncio.wait_for(
                    hitl_queue.get(), timeout=_HITL_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logger.warning("[SSE] HITL timeout [session=%s]", session_id)
                yield _sse(StreamEvent(
                    event=StreamEventType.ERROR,
                    data={"error": "HITL 응답 대기 시간이 초과되었습니다."},
                    session_id=session_id,
                ))
                break

            yield _sse(StreamEvent(
                event=StreamEventType.HUMAN_INPUT_RECEIVED,
                data={"response": user_response},
                session_id=session_id,
            ))
            await asyncio.sleep(0)

            current_input = Command(resume=user_response)

    except Exception as e:
        logger.exception("[SSE] 스트리밍 오류 [session=%s]", session_id)
        yield _sse(StreamEvent(
            event=StreamEventType.ERROR,
            data={"error": str(e)},
            session_id=session_id,
        ))
    finally:
        hitl_manager.unregister(session_id)

    yield _sse_raw({"event": "done", "data": {}, "session_id": session_id})
