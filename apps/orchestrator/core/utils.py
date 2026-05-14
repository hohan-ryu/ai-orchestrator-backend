import json
import re
import logging
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


def extract_json(text: str) -> str:
    """응답 텍스트에서 JSON 블록을 추출합니다 (마크다운 코드블록 포함)."""
    block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if block:
        return block.group(1).strip()
    obj = re.search(r"\{[\s\S]*\}", text)
    if obj:
        return obj.group(0)
    return text.strip()


def safe_parse_json(text: str) -> dict:
    """LLM 응답에서 JSON을 안전하게 파싱합니다. 실패 시 ValueError를 발생시킵니다."""
    cleaned = extract_json(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {e}\n원본 텍스트:\n{text[:200]}")


async def invoke_llm(llm: BaseChatModel, system: str, user: str) -> str:
    """LLM을 호출하고 텍스트 응답을 반환하는 공통 헬퍼입니다."""
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user),
    ]
    response = await llm.ainvoke(messages)
    return response.content
