import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apps.orchestrator.config import get_settings
from apps.orchestrator.api.routes import router

_logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# 파일 핸들러 준비 (아직 루트 로거에 붙이지 않음)
# uvicorn이 자체 로깅을 마친 뒤 lifespan에서 등록합니다.
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).resolve().parents[2]   # 프로젝트 루트
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_formatter = logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

_file_handler = logging.handlers.RotatingFileHandler(
    _LOG_DIR / "app.log",
    maxBytes=10 * 1024 * 1024,   # 10 MB
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(_formatter)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 파일 핸들러 등록 (uvicorn 로깅 설정 완료 후)
    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(_file_handler)
        root.setLevel(logging.INFO)

    _logger.info("앱 시작 — 로그 파일: %s/app.log", _LOG_DIR)

    # 2. LangGraph 그래프 초기화
    from apps.orchestrator.core.graph import build_graph, set_graph
    if settings.redis_enabled:
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver
            saver = AsyncRedisSaver(redis_url=settings.redis_url)
            await saver.asetup()
            set_graph(build_graph(saver))
            _logger.info("[Graph] AsyncRedisSaver 체크포인터 활성화: %s", settings.redis_url)
        except Exception as e:
            _logger.warning("[Graph] AsyncRedisSaver 초기화 실패 → MemorySaver 사용: %s", e)
            set_graph(build_graph())
    else:
        set_graph(build_graph())

    yield
    _logger.info("앱 종료")


# ---------------------------------------------------------------------------
# FastAPI 앱
# ---------------------------------------------------------------------------

class UTF8JSONResponse(JSONResponse):
    """Content-Type에 charset=utf-8을 명시합니다."""
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="AI Orchestrator",
    description="자연어 요청을 분석하고 LangGraph 기반으로 작업을 계획·실행하는 AI 오케스트레이터",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _logger.exception("처리되지 않은 예외 발생 [%s %s]", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"서버 내부 오류: {type(exc).__name__}: {exc}"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
