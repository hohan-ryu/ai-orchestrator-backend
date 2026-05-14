import logging
from langgraph.types import interrupt
from apps.orchestrator.config import get_settings
from apps.orchestrator.core.state import OrchestratorState
from apps.orchestrator.intent.pipeline import run_pipeline
from apps.orchestrator.schemas.models import StreamEvent, StreamEventType, HITLPayload

logger = logging.getLogger(__name__)

# tier → StreamEventType 매핑
_TIER_EVENT = {
    "rule": StreamEventType.INTENT_FROM_RULE,
    "cache": StreamEventType.INTENT_FROM_CACHE,
    "llm": StreamEventType.INTENT_FROM_LLM,
}


async def analyze_intent(state: OrchestratorState) -> dict:
    settings = get_settings()

    intent, tier = await run_pipeline(state["user_input"], settings)

    # 신뢰도가 낮으면 사용자에게 의도 확인 요청 (HITL)
    if intent.confidence < settings.hitl_clarify_threshold:
        hitl = HITLPayload(
            type="intent_clarification",
            question=(
                f"요청 의도를 명확히 파악하기 어렵습니다 (신뢰도: {intent.confidence:.0%}).\n"
                f"현재 분석된 의도: [{intent.category}] {intent.summary}\n"
                "계속 진행하려면 'yes', 직접 입력하려면 원하는 작업을 설명해 주세요."
            ),
            options=["yes", "직접 입력"],
            context={"analyzed_intent": intent.model_dump()},
        )
        user_response = interrupt(hitl.model_dump())

        # 사용자가 'yes' 또는 빈 입력이면 그대로 진행
        if str(user_response).strip().lower() not in ("yes", "y", "네", "예", ""):
            # 사용자가 직접 의도를 다시 입력한 경우 재분석
            intent, tier = await run_pipeline(str(user_response), settings)

    tier_event = _TIER_EVENT.get(tier, StreamEventType.INTENT_ANALYZED)

    return {
        "intent": intent,
        "intent_tier": tier,
        "stream_events": [StreamEvent(
            event=tier_event,
            data={**intent.model_dump(), "tier": tier},
            session_id=state["session_id"],
        )],
    }
