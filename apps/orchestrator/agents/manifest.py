"""
에이전트 표준 매니페스트 스키마.
모든 에이전트 타입(api / mcp / file)이 공유하는 정의입니다.
"""

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class AgentToolParam(BaseModel):
    type: str = "string"
    description: str = ""
    default: Any = None


class AgentTool(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class APIConfig(BaseModel):
    url: str
    timeout: int = 30
    auth_type: Literal["none", "bearer", "api_key", "basic"] = "none"
    auth_token: str = ""
    auth_header: str = "Authorization"
    execute_path: str = "/execute"
    tools_path: str = "/tools"
    health_path: str = "/health"


class MCPConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout: int = 30


class AgentManifest(BaseModel):
    id: str = Field(..., description="고유 식별자 (파일명 기반 권장)")
    name: str
    description: str = ""
    version: str = "1.0.0"
    type: Literal["api", "mcp", "file"]
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
    tools: list[AgentTool] = Field(default_factory=list)

    # 타입별 설정 (해당 타입이 아니면 None)
    api: APIConfig | None = None
    mcp: MCPConfig | None = None

    # file 타입용 (agent.md 본문에서 추출)
    system_prompt: str = ""

    # 런타임 메타데이터 (코드에서 채움, 사용자 정의 불필요)
    source_path: str = ""


class AgentResult(BaseModel):
    success: bool
    output: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    agent_id: str = ""
    tool: str = ""
