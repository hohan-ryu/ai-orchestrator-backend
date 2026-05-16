"""
Orchestrator API 라우터.

스트리밍(SSE) 및 HITL 관련 엔드포인트를 제공합니다.

POST /orchestrate/stream             — SSE 스트리밍 실행
POST /orchestrate/resume/{session}   — HITL 사용자 응답 전달
GET  /orchestrate/token-usage        — LLM 토큰 사용량 조회
DEL  /orchestrate/token-usage        — 토큰 사용량 초기화
POST /orchestrate/run                — 비스트리밍 단일 응답 (HITL 없음)
GET  /orchestrate/sessions           — 현재 HITL 대기 중인 세션 목록
"""

import uuid
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from apps.orchestrator.common.schemas.models import (
    OrchestrateRequest, OrchestrateResponse, ResumeRequest,
)
from apps.orchestrator.core.graph import get_graph
from apps.orchestrator.llms import get_gateway
from apps.orchestrator.streaming.hitl import hitl_manager
from apps.orchestrator.streaming.sse import stream_graph, make_initial_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestrate", tags=["orchestrator"])


@router.post("/stream")
async def orchestrate_stream(request: OrchestrateRequest):
    """자연어 요청을 받아 LangGraph로 처리하고 SSE로 진행 상황을 스트리밍합니다."""
    session_id = request.session_id or str(uuid.uuid4())
    hitl_queue = hitl_manager.register(session_id)
    return StreamingResponse(
        stream_graph(request, session_id, hitl_queue),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
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


@router.get("/sessions")
async def list_active_sessions():
    """현재 HITL 응답을 대기 중인 세션 목록을 반환합니다."""
    return {
        "sessions": hitl_manager.active_sessions,
        "count": len(hitl_manager.active_sessions),
    }


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
    initial_state = make_initial_state(request, session_id)

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
