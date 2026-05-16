"""
LLM Provider 설정 스키마.

각 provider는 JSON 파일(llm_providers.json)에 저장되며
Admin API를 통해 CRUD됩니다. 소스코드 변경 없이 endpoint를 추가/변경할 수 있습니다.
"""

import hashlib
import json
from typing import Literal
from pydantic import BaseModel, Field, model_validator


AdapterType = Literal["google", "anthropic", "ollama", "openai", "local", "mock"]
CapabilityType = Literal["completion", "embedding", "both"]


class LLMProviderConfig(BaseModel):
    # 식별
    id: str = Field(..., description="고유 식별자 (영문, 숫자, 하이픈)")
    name: str = Field("", description="화면에 표시할 이름")
    description: str = Field("", description="설명")

    # 어댑터 유형
    adapter: AdapterType = Field(..., description="어댑터 종류: google | anthropic | ollama | openai | local | mock")
    capability: CapabilityType = Field("completion", description="지원 기능: completion | embedding | both")

    # 활성화 / 우선순위
    enabled: bool = Field(True, description="활성화 여부")
    priority: int = Field(0, description="낮을수록 먼저 시도 (0 = 최우선)")
    is_fallback: bool = Field(False, description="True이면 앞 provider 전부 실패 시에만 사용")

    # 연결 정보
    base_url: str = Field("", description="커스텀/Ollama endpoint URL (예: http://localhost:11434)")
    api_key: str = Field("", description="API 키 (Fernet 암호화 저장). ${ENV_VAR} 형식으로 환경변수 참조 가능")

    # 모델
    model: str = Field("", description="기본 completion 모델명")
    embedding_model: str = Field("", description="임베딩 모델명 (비어있으면 model 사용)")

    # LLM 파라미터
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    timeout: int = Field(60, gt=0, description="요청 타임아웃 (초)")
    max_retries: int = Field(1, ge=0, description="실패 시 재시도 횟수")

    # 메타
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_adapter_requirements(self) -> "LLMProviderConfig":
        if self.adapter in ("google", "anthropic", "openai") and not self.api_key:
            # api_key 없어도 저장은 허용 (나중에 입력 가능)
            pass
        if self.adapter == "local" and self.capability not in ("embedding", "both"):
            raise ValueError("local 어댑터는 capability가 'embedding' 또는 'both'여야 합니다.")
        return self

    def config_hash(self) -> str:
        """설정 내용의 MD5 해시 — 어댑터 캐시 무효화에 사용합니다."""
        payload = self.model_dump(exclude={"name", "description", "tags"})
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(serialized.encode()).hexdigest()

    def supports_completion(self) -> bool:
        return self.capability in ("completion", "both")

    def supports_embedding(self) -> bool:
        return self.capability in ("embedding", "both")


# ---------------------------------------------------------------------------
# 요청/응답 모델 (API 전용)
# ---------------------------------------------------------------------------

class ProviderCreateRequest(BaseModel):
    """신규 provider 등록 요청. api_key는 평문으로 받아 서버에서 암호화합니다."""
    id: str
    name: str = ""
    description: str = ""
    adapter: AdapterType
    capability: CapabilityType = "completion"
    enabled: bool = True
    priority: int = 0
    is_fallback: bool = False
    base_url: str = ""
    api_key: str = Field("", description="평문 API 키 (서버에서 Fernet 암호화)")
    model: str = ""
    embedding_model: str = ""
    temperature: float = 0.0
    timeout: int = 60
    max_retries: int = 1
    tags: list[str] = []


class ProviderUpdateRequest(BaseModel):
    """provider 수정 요청. 제공된 필드만 업데이트합니다."""
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    is_fallback: bool | None = None
    base_url: str | None = None
    api_key: str | None = Field(None, description="평문 API 키. None이면 기존 값 유지")
    model: str | None = None
    embedding_model: str | None = None
    temperature: float | None = None
    timeout: int | None = None
    max_retries: int | None = None
    tags: list[str] | None = None


class ProviderResponse(BaseModel):
    """API 응답용. api_key는 마스킹합니다."""
    id: str
    name: str
    description: str
    adapter: str
    capability: str
    enabled: bool
    priority: int
    is_fallback: bool
    base_url: str
    api_key_set: bool           # api_key가 설정되었는지 여부만 노출
    model: str
    embedding_model: str
    temperature: float
    timeout: int
    max_retries: int
    tags: list[str]

    @classmethod
    def from_config(cls, cfg: LLMProviderConfig) -> "ProviderResponse":
        return cls(
            **{k: v for k, v in cfg.model_dump().items() if k != "api_key"},
            api_key_set=bool(cfg.api_key),
        )
