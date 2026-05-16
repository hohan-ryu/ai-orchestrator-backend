from pydantic import BaseModel, Field
from typing import Any
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StreamEventType(str, Enum):
    # 의도 분석 (tier 정보 포함)
    INTENT_ANALYZED = "intent_analyzed"       # 공통
    INTENT_FROM_RULE = "intent_from_rule"     # Tier 1
    INTENT_FROM_CACHE = "intent_from_cache"   # Tier 2
    INTENT_FROM_LLM = "intent_from_llm"       # Tier 3

    # 작업 계획/실행
    PLAN_CREATED = "plan_created"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    EXECUTION_COMPLETED = "execution_completed"

    # Human-in-the-Loop
    HUMAN_INPUT_REQUIRED = "human_input_required"
    HUMAN_INPUT_RECEIVED = "human_input_received"

    ERROR = "error"


# --- Request ---

class OrchestrateRequest(BaseModel):
    message: str = Field(..., description="사용자 자연어 입력", min_length=1)
    session_id: str | None = Field(None, description="세션 ID (없으면 자동 생성)")


class ResumeRequest(BaseModel):
    response: str = Field(..., description="HITL 질문에 대한 사용자 응답")


# --- Inner Models ---

class Intent(BaseModel):
    category: str = Field(..., description="의도 분류")
    summary: str = Field(..., description="의도 요약")
    entities: dict[str, Any] = Field(default_factory=dict, description="추출된 핵심 엔티티")
    confidence: float = Field(..., ge=0.0, le=1.0, description="분석 신뢰도")


class Task(BaseModel):
    id: str = Field(..., description="태스크 ID")
    title: str = Field(..., description="태스크 제목")
    description: str = Field(..., description="태스크 설명")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    result: str | None = None
    error: str | None = None
    # 에이전트 라우팅 (None이면 LLM 직접 실행)
    agent_id: str | None = Field(None, description="실행할 에이전트 ID")
    agent_tool: str | None = Field(None, description="호출할 에이전트 툴명")
    agent_input: dict[str, Any] = Field(default_factory=dict, description="에이전트 툴 입력 파라미터")


class TaskPlan(BaseModel):
    tasks: list[Task] = Field(default_factory=list)
    total: int = 0
    reasoning: str = Field("", description="계획 수립 근거")


# --- SSE Streaming ---

class StreamEvent(BaseModel):
    event: StreamEventType
    data: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


# --- HITL ---

class HITLPayload(BaseModel):
    """HITL 이벤트에 담기는 질문/옵션 정보"""
    type: str = Field(..., description="hitl 타입: plan_confirmation | intent_clarification")
    question: str
    options: list[str] = Field(default_factory=list, description="선택 가능한 옵션 (비어있으면 자유 입력)")
    context: dict[str, Any] = Field(default_factory=dict, description="추가 컨텍스트")


# --- Response ---

class OrchestrateResponse(BaseModel):
    session_id: str
    intent: Intent | None = None
    intent_tier: str | None = Field(None, description="의도 분석에 사용된 tier: rule | cache | llm")
    plan: TaskPlan | None = None
    final_answer: str = ""
    success: bool = True
    error: str | None = None
