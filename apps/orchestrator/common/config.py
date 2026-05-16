from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM Provider: "google" | "anthropic"
    llm_provider: str = "google"

    # API Keys
    google_api_key: str = ""
    anthropic_api_key: str = ""

    # Chat Models
    intent_model: str = "gemini-2.5-flash"
    planner_model: str = "gemini-2.5-flash"
    executor_model: str = "gemini-2.5-flash"

    # Embedding
    embedding_provider: str = "mock"            # "mock" | "local" | "google"
    embedding_model: str = "models/text-embedding-004"   # Google API 모델명
    embedding_model_local: str = "BAAI/bge-m3"           # FastEmbed 모델명
    embedding_similarity_threshold: float = 0.92

    # LLM 공통 옵션
    llm_max_retries: int = 3
    llm_temperature: float = 0.0

    # Orchestrator
    max_tasks: int = 10
    task_timeout: int = 30

    # LLM Gateway
    gateway_mode: str = "auto"             # "auto" | "mock"  (.env: GATEWAY_MODE=mock)
    gateway_fallback_to_mock: bool = True  # 프로바이더 오류 시 Mock으로 자동 fallback

    # Redis (LangGraph 체크포인터 — 세션 상태 영속화)
    redis_url: str = "redis://localhost:6379"
    redis_enabled: bool = False            # .env: REDIS_ENABLED=true

    # Qdrant (임베딩 벡터 유사도 검색)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_enabled: bool = False           # .env: QDRANT_ENABLED=true
    qdrant_collection: str = "intent_cache"
    qdrant_vector_size: int = 768          # mock/google=768, BAAI/bge-m3=1024

    # Agent Registry
    agents_dir: str = "agents"              # 에이전트 정의 파일 디렉토리 (프로젝트 루트 기준)

    # LLM Provider Registry
    llm_providers_file: str = "llm_providers.json"  # LLM provider 설정 파일 (프로젝트 루트 기준)

    # Human-in-the-Loop
    hitl_confirm_plan: bool = True          # 실행 전 플랜 사용자 확인
    hitl_clarify_threshold: float = 0.5    # 신뢰도 미달 시 사용자에게 의도 확인 요청

    # Security
    encryption_key: str = ""               # Fernet key (base64). 빈 값이면 암호화 비활성화.

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
