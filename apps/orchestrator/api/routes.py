import hashlib
import uuid
import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from apps.orchestrator.schemas.models import (
    OrchestrateRequest, OrchestrateResponse, ResumeRequest,
    StreamEvent, StreamEventType,
)
from apps.orchestrator.core.graph import get_graph
from apps.orchestrator.llm_gateway import get_gateway, reset_gateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestrate", tags=["orchestrator"])


class HITLManager:
    """세션별 HITL 응답 큐를 관리합니다."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def register(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues[session_id] = q
        return q

    async def send_response(self, session_id: str, response: str) -> bool:
        q = self._queues.get(session_id)
        if q is None:
            return False
        await q.put(response)
        return True

    def unregister(self, session_id: str) -> None:
        self._queues.pop(session_id, None)


hitl_manager = HITLManager()


def _make_initial_state(request: OrchestrateRequest, session_id: str) -> dict:
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


async def _stream_graph(request: OrchestrateRequest, session_id: str, hitl_queue: asyncio.Queue):
    """LangGraph 실행 결과를 SSE 형식으로 스트리밍합니다. HITL interrupt를 처리합니다."""
    config = {"configurable": {"thread_id": session_id}}
    current_input = _make_initial_state(request, session_id)
    seen_event_ids: set[str] = set()

    try:
        while True:
            async for chunk in get_graph().astream(current_input, config, stream_mode="updates"):
                # HITL interrupt 감지
                if "__interrupt__" in chunk:
                    for interrupt_obj in chunk["__interrupt__"]:
                        hitl_payload = interrupt_obj.value
                        event = StreamEvent(
                            event=StreamEventType.HUMAN_INPUT_REQUIRED,
                            data=hitl_payload if isinstance(hitl_payload, dict) else hitl_payload,
                            session_id=session_id,
                        )
                        yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0)
                    continue

                # 일반 노드 출력에서 stream_events 추출
                for node_output in chunk.values():
                    if not isinstance(node_output, dict):
                        continue
                    for event in node_output.get("stream_events", []):
                        # 콘텐츠 기반 해시로 HITL 재실행 시 동일 이벤트 중복 방지
                        serialized = json.dumps(event.model_dump(), ensure_ascii=False, sort_keys=True)
                        event_key = hashlib.md5(serialized.encode()).hexdigest()
                        if event_key in seen_event_ids:
                            continue
                        seen_event_ids.add(event_key)
                        yield f"data: {serialized}\n\n"
                        await asyncio.sleep(0)

            # 그래프 상태 확인: 다음 노드가 있으면 interrupt 상태
            graph_state = await get_graph().aget_state(config)
            if graph_state.next:
                # HITL 응답 대기 (최대 10분)
                try:
                    user_response = await asyncio.wait_for(hitl_queue.get(), timeout=600)
                except asyncio.TimeoutError:
                    logger.warning("HITL timeout for session %s", session_id)
                    break

                # 사용자 응답 수신 이벤트 전송
                received_event = StreamEvent(
                    event=StreamEventType.HUMAN_INPUT_RECEIVED,
                    data={"response": user_response},
                    session_id=session_id,
                )
                yield f"data: {json.dumps(received_event.model_dump(), ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)

                current_input = Command(resume=user_response)
            else:
                break

    except Exception as e:
        logger.exception("스트리밍 중 오류 발생 [session=%s]", session_id)
        error_event = StreamEvent(
            event=StreamEventType.ERROR,
            data={"error": str(e)},
            session_id=session_id,
        )
        yield f"data: {json.dumps(error_event.model_dump(), ensure_ascii=False)}\n\n"
    finally:
        hitl_manager.unregister(session_id)

    yield f"data: {json.dumps({'event': 'done', 'data': {}, 'session_id': session_id})}\n\n"


@router.post("/stream")
async def orchestrate_stream(request: OrchestrateRequest):
    """자연어 요청을 받아 LangGraph로 처리하고 SSE로 진행 상황을 스트리밍합니다."""
    session_id = request.session_id or str(uuid.uuid4())
    hitl_queue = hitl_manager.register(session_id)
    return StreamingResponse(
        _stream_graph(request, session_id, hitl_queue),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Session-Id": session_id,
        },
    )


@router.post("/resume/{session_id}")
async def resume_orchestration(session_id: str, body: ResumeRequest):
    """HITL 일시 중지된 그래프에 사용자 응답을 전달하여 실행을 재개합니다."""
    success = await hitl_manager.send_response(session_id, body.response)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"세션 '{session_id}'을 찾을 수 없거나 입력을 기다리지 않습니다.",
        )
    return {"status": "ok", "session_id": session_id}


@router.get("/token-usage")
async def get_token_usage():
    """LLM Gateway 누적 토큰 사용량을 조회합니다."""
    return get_gateway().token_tracker.summary()


@router.delete("/token-usage")
async def reset_token_usage():
    """LLM Gateway 토큰 사용량 카운터를 초기화합니다."""
    get_gateway().token_tracker.reset()
    return {"status": "ok", "message": "토큰 사용량이 초기화되었습니다."}


@router.post("/run", response_model=OrchestrateResponse)
async def orchestrate_run(request: OrchestrateRequest):
    """자연어 요청을 처리하고 최종 결과를 한 번에 반환합니다 (non-streaming, HITL 없음)."""
    session_id = request.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}
    initial_state = _make_initial_state(request, session_id)

    final_state = await get_graph().ainvoke(initial_state, config)

    return OrchestrateResponse(
        session_id=session_id,
        intent=final_state.get("intent"),
        intent_tier=final_state.get("intent_tier"),
        plan=final_state.get("plan"),
        final_answer=final_state.get("final_answer", ""),
        success=final_state.get("error") is None,
        error=final_state.get("error"),
    )
