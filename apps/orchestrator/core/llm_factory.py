from langchain_core.language_models import BaseChatModel
from apps.orchestrator.config import Settings

# quota 에러(429)는 재시도해도 의미 없으므로 일시적 오류(5xx, timeout)만 retry 대상으로 지정
_GOOGLE_RETRY_EXCEPTIONS: tuple = ()
_ANTHROPIC_RETRY_EXCEPTIONS: tuple = ()

try:
    from google.api_core.exceptions import ServiceUnavailable, DeadlineExceeded, InternalServerError as GoogleInternalError
    _GOOGLE_RETRY_EXCEPTIONS = (ServiceUnavailable, DeadlineExceeded, GoogleInternalError)
except ImportError:
    pass

try:
    from anthropic import APITimeoutError, InternalServerError as AnthropicInternalError
    _ANTHROPIC_RETRY_EXCEPTIONS = (APITimeoutError, AnthropicInternalError)
except ImportError:
    pass


def get_llm(model: str, settings: Settings) -> BaseChatModel:
    """provider 설정에 따라 적절한 LangChain LLM 인스턴스를 반환합니다."""
    provider = settings.llm_provider

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
            temperature=settings.llm_temperature,
        )
        retry_exceptions = _GOOGLE_RETRY_EXCEPTIONS
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            temperature=settings.llm_temperature,
        )
        retry_exceptions = _ANTHROPIC_RETRY_EXCEPTIONS
    else:
        raise ValueError(f"지원하지 않는 LLM provider: '{provider}'. 'google' 또는 'anthropic'을 사용하세요.")

    if retry_exceptions and settings.llm_max_retries > 1:
        return llm.with_retry(
            retry_if_exception_type=retry_exceptions,
            stop_after_attempt=settings.llm_max_retries,
        )
    return llm
