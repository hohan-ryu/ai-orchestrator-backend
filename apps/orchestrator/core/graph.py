import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphBubbleUp
from apps.orchestrator.common.config import get_settings
from apps.orchestrator.core.state import OrchestratorState
from apps.orchestrator.core.nodes.intent_analyzer import analyze_intent
from apps.orchestrator.core.nodes.task_planner import plan_tasks
from apps.orchestrator.core.nodes.task_executor import execute_tasks
from apps.orchestrator.common.schemas.models import StreamEvent, StreamEventType

logger = logging.getLogger(__name__)


async def handle_error(state: OrchestratorState) -> dict:
    error_msg = state.get("error", "알 수 없는 오류가 발생했습니다.")
    logger.error("Orchestrator 치명적 오류: %s", error_msg)
    return {
        "final_answer": f"요청 처리 중 오류가 발생했습니다: {error_msg}",
        "stream_events": [StreamEvent(
            event=StreamEventType.ERROR,
            data={"error": error_msg},
            session_id=state.get("session_id"),
        )],
    }


def _wrap_node(node_fn, node_name: str):
    """노드 예외를 error 상태로 변환합니다. GraphBubbleUp(interrupt 포함)은 반드시 재전파합니다."""
    async def wrapped(state: OrchestratorState) -> dict:
        try:
            return await node_fn(state)
        except GraphBubbleUp:
            raise
        except Exception as e:
            logger.exception("노드 [%s] 예외 발생", node_name)
            return {"error": f"[{node_name}] {e}"}
    wrapped.__name__ = node_fn.__name__
    return wrapped


def _should_continue(state: OrchestratorState) -> str:
    return "error" if state.get("error") else "continue"


def build_graph(checkpointer=None):
    """
    checkpointer가 주어지면 그것을 사용하고, 없으면 MemorySaver를 씁니다.
    AsyncRedisSaver처럼 await가 필요한 체크포인터는 lifespan에서 초기화 후 전달합니다.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()
        logger.info("[Graph] MemorySaver 체크포인터 사용")

    graph = StateGraph(OrchestratorState)

    graph.add_node("analyze_intent", _wrap_node(analyze_intent, "의도분석"))
    graph.add_node("plan_tasks", _wrap_node(plan_tasks, "작업계획"))
    graph.add_node("execute_tasks", _wrap_node(execute_tasks, "태스크실행"))
    graph.add_node("handle_error", handle_error)

    graph.set_entry_point("analyze_intent")

    graph.add_conditional_edges(
        "analyze_intent",
        _should_continue,
        {"continue": "plan_tasks", "error": "handle_error"},
    )
    graph.add_conditional_edges(
        "plan_tasks",
        _should_continue,
        {"continue": "execute_tasks", "error": "handle_error"},
    )
    graph.add_edge("execute_tasks", END)
    graph.add_edge("handle_error", END)

    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# 싱글턴 — lifespan에서 set_graph()로 주입하거나 get_graph()로 lazy 초기화합니다.
# ---------------------------------------------------------------------------
_graph = None


def set_graph(graph) -> None:
    """lifespan에서 비동기 체크포인터(AsyncRedisSaver 등)로 초기화된 그래프를 주입합니다."""
    global _graph
    _graph = graph


def get_graph():
    global _graph
    if _graph is None:
        logger.info("[Graph] 그래프 lazy 초기화 (MemorySaver)")
        _graph = build_graph()
    return _graph
