import logging
from langgraph.types import interrupt
from apps.orchestrator.config import get_settings
from apps.orchestrator.core.state import OrchestratorState
from apps.orchestrator.llm_gateway import get_gateway
from apps.orchestrator.schemas.models import Task, TaskStatus, StreamEvent, StreamEventType, HITLPayload

logger = logging.getLogger(__name__)

_EXEC_SYSTEM = """당신은 주어진 태스크를 실행하는 전문 에이전트입니다.
태스크를 완전히 수행하고 결과를 명확하게 서술하세요.
이전 태스크의 결과를 참고하여 일관성 있게 작업하세요."""

_SUMMARY_SYSTEM = """당신은 여러 태스크의 실행 결과를 종합하여 사용자에게 최종 답변을 제공하는 전문가입니다.
실행된 모든 태스크의 결과를 바탕으로, 사용자의 원래 요청에 대한 명확하고 완결된 답변을 작성하세요.
마크다운 형식을 활용하여 읽기 쉽게 구성하세요."""


def _is_confirmed(response: str) -> bool:
    return str(response).strip().lower() in ("yes", "y", "네", "예", "ok", "확인", "진행", "")


async def execute_tasks(state: OrchestratorState) -> dict:
    settings = get_settings()
    gateway = get_gateway(settings)
    plan = state["plan"]
    stream_events: list[StreamEvent] = []

    # --- HITL: 플랜 실행 전 사용자 확인 ---
    if settings.hitl_confirm_plan:
        task_list = "\n".join(
            f"  {i+1}. {t.title}: {t.description}"
            for i, t in enumerate(plan.tasks)
        )
        hitl = HITLPayload(
            type="plan_confirmation",
            question=(
                f"다음 {plan.total}개의 작업을 실행하시겠습니까?\n\n"
                f"{task_list}\n\n"
                "진행하려면 'yes', 취소하려면 'no'를 입력하세요."
            ),
            options=["yes", "no"],
            context={"plan": plan.model_dump()},
        )
        confirmation = interrupt(hitl.model_dump())

        if not _is_confirmed(confirmation):
            cancelled_msg = "사용자가 작업 실행을 취소했습니다."
            stream_events.append(StreamEvent(
                event=StreamEventType.EXECUTION_COMPLETED,
                data={"final_answer": cancelled_msg, "cancelled": True},
                session_id=state["session_id"],
            ))
            return {
                "final_answer": cancelled_msg,
                "stream_events": stream_events,
            }

    # --- 태스크 순차 실행 ---
    completed_tasks: list[Task] = []
    context_parts: list[str] = []

    for task in plan.tasks:
        task.status = TaskStatus.RUNNING
        stream_events.append(StreamEvent(
            event=StreamEventType.TASK_STARTED,
            data={"task_id": task.id, "title": task.title},
            session_id=state["session_id"],
        ))

        try:
            user_content = (
                f"원래 사용자 요청: {state['user_input']}\n\n"
                f"이전 태스크 결과:\n{chr(10).join(context_parts) or '없음'}\n\n"
                f"현재 수행할 태스크:\n제목: {task.title}\n설명: {task.description}"
            )
            response = await gateway.complete(settings.executor_model, _EXEC_SYSTEM, user_content)
            result = response.content
            task.status = TaskStatus.COMPLETED
            task.result = result
            context_parts.append(f"[{task.title}]: {result}")

            stream_events.append(StreamEvent(
                event=StreamEventType.TASK_COMPLETED,
                data={"task_id": task.id, "title": task.title, "result": result},
                session_id=state["session_id"],
            ))

        except Exception as e:
            logger.error("태스크 실행 실패 [%s]: %s", task.title, e)
            task.status = TaskStatus.FAILED
            task.error = str(e)
            context_parts.append(f"[{task.title}]: 실패 - {e}")

            stream_events.append(StreamEvent(
                event=StreamEventType.TASK_FAILED,
                data={"task_id": task.id, "title": task.title, "error": str(e)},
                session_id=state["session_id"],
            ))

        completed_tasks.append(task)

    # --- 최종 답변 생성 ---
    results_summary = "\n\n".join(
        f"**태스크 {i+1}: {t.title}**\n{t.result or f'[실패] {t.error}'}"
        for i, t in enumerate(completed_tasks)
    )

    try:
        summary_response = await gateway.complete(
            settings.executor_model,
            _SUMMARY_SYSTEM,
            f"원래 요청: {state['user_input']}\n\n태스크 실행 결과:\n{results_summary}",
        )
        final_answer = summary_response.content
    except Exception as e:
        logger.error("최종 답변 생성 실패: %s", e)
        final_answer = f"처리 결과:\n\n{results_summary}"

    stream_events.append(StreamEvent(
        event=StreamEventType.EXECUTION_COMPLETED,
        data={"final_answer": final_answer},
        session_id=state["session_id"],
    ))

    return {
        "completed_tasks": completed_tasks,
        "final_answer": final_answer,
        "stream_events": stream_events,
    }
