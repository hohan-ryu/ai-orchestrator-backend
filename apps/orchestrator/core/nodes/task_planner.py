import json
import uuid
import logging
from apps.orchestrator.config import get_settings
from apps.orchestrator.core.state import OrchestratorState
from apps.orchestrator.llm_gateway import get_gateway
from apps.orchestrator.core.utils import safe_parse_json
from apps.orchestrator.schemas.models import Task, TaskPlan, TaskStatus, StreamEvent, StreamEventType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 사용자의 요청을 달성하기 위한 실행 계획을 수립하는 전문가입니다.

다음 JSON 형식으로만 응답하세요:
{{
  "reasoning": "이 계획을 수립한 근거",
  "tasks": [
    {{
      "title": "태스크 제목 (짧고 명확하게)",
      "description": "태스크 상세 설명 (무엇을, 어떻게 할지)",
      "agent_id": "에이전트 ID 또는 null",
      "agent_tool": "툴명 또는 null",
      "agent_input": {{}}
    }}
  ]
}}

규칙:
- 태스크는 순차적으로 실행됩니다
- 각 태스크는 독립적으로 완료 가능해야 합니다
- 최소 1개, 최대 {max_tasks}개의 태스크로 구성하세요
- 사용 가능한 에이전트가 있으면 적합한 태스크에 우선 배정하세요 (agent_id, agent_tool, agent_input 지정)
- 에이전트 없이 LLM이 직접 처리할 태스크는 agent_id를 null로 설정하세요
- JSON 외에 다른 텍스트는 포함하지 마세요{agents_section}"""

_AGENTS_SECTION_TMPL = """

사용 가능한 에이전트:
{agents_list}
각 에이전트의 툴을 적절한 태스크에 배정하세요."""


def _format_agents(manifests) -> str:
    if not manifests:
        return ""
    lines = []
    for m in manifests:
        tools = ", ".join(t.name for t in m.tools) or "없음"
        lines.append(f"  - id: {m.id} | 타입: {m.type} | 설명: {m.description} | 툴: [{tools}]")
    return _AGENTS_SECTION_TMPL.format(agents_list="\n".join(lines))


def _make_fallback_plan(user_input: str) -> TaskPlan:
    return TaskPlan(
        tasks=[Task(
            id=str(uuid.uuid4()),
            title="요청 처리",
            description=user_input,
            status=TaskStatus.PENDING,
        )],
        total=1,
        reasoning="작업 계획 수립에 실패하여 단일 태스크로 처리합니다.",
    )


async def plan_tasks(state: OrchestratorState) -> dict:
    settings = get_settings()
    gateway = get_gateway(settings)
    intent = state["intent"]

    from apps.orchestrator.agents.registry import get_registry
    registry = get_registry()
    agents_section = _format_agents(registry.list_enabled()) if registry else ""

    system = _SYSTEM_PROMPT.format(max_tasks=settings.max_tasks, agents_section=agents_section)
    user_content = (
        f"사용자 요청: {state['user_input']}\n\n"
        f"의도 분석 결과:\n"
        f"- 분류: {intent.category}\n"
        f"- 요약: {intent.summary}\n"
        f"- 핵심 엔티티: {json.dumps(intent.entities, ensure_ascii=False)}"
    )

    try:
        response = await gateway.complete(settings.planner_model, system, user_content)
        parsed = safe_parse_json(response.content)
        tasks = [
            Task(
                id=str(uuid.uuid4()),
                title=t["title"],
                description=t["description"],
                status=TaskStatus.PENDING,
                agent_id=t.get("agent_id") or None,
                agent_tool=t.get("agent_tool") or None,
                agent_input=t.get("agent_input") or {},
            )
            for t in parsed["tasks"]
        ]
        plan = TaskPlan(
            tasks=tasks,
            total=len(tasks),
            reasoning=parsed.get("reasoning", ""),
        )
    except Exception as e:
        logger.warning("태스크 계획 수립 실패, fallback 사용: %s", e)
        plan = _make_fallback_plan(state["user_input"])

    return {
        "plan": plan,
        "stream_events": [StreamEvent(
            event=StreamEventType.PLAN_CREATED,
            data=plan.model_dump(),
            session_id=state["session_id"],
        )],
    }
