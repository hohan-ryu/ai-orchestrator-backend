from typing import Annotated
from typing_extensions import TypedDict
from apps.orchestrator.schemas.models import Intent, Task, TaskPlan, StreamEvent


class OrchestratorState(TypedDict):
    # 사용자 입력
    user_input: str
    session_id: str

    # 의도 분석 결과
    intent: Intent | None
    intent_tier: str | None   # "rule" | "cache" | "llm"

    # 작업 계획
    plan: TaskPlan | None

    # 실행 완료된 태스크 (append 방식으로 누적)
    completed_tasks: Annotated[list[Task], lambda x, y: x + y]

    # 최종 답변
    final_answer: str

    # 스트리밍 이벤트 큐 (누적)
    stream_events: Annotated[list[StreamEvent], lambda x, y: x + y]

    # 치명적 오류
    error: str | None
