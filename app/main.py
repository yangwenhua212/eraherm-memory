# Copyright (c) 2026 Wenhua Yang (杨文华)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router
from app.config import get_settings
from app.container import build_container
from app.observability.logging import logger
from app.observability.middleware import RequestContextMiddleware
from app.ratelimit import RateLimitMiddleware, TokenBucketLimiter
from app.security import exposure_problem, token_is_configured


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = build_container()
    app.state.container = container
    app.state.memory_service = container.memory_service
    app.state.graph_service = container.graph_service
    app.state.feedback_service = container.feedback_service
    app.state.l3_service = container.l3_service
    app.state.consolidation_service = container.consolidation_service
    app.state.watchdog_service = container.watchdog_service
    app.state.settings = container.settings
    if not token_is_configured(container.settings.admin_token):
        logger.warning(
            "admin_endpoints_disabled",
            extra={
                "detail": (
                    "ERAHERM_ADMIN_TOKEN 未配置（或仍是占位值）→ /v1/admin/* 一律返回 503。"
                    "需要 consolidate / watchdog / reembed / l3 时请设置一个真实密钥。"
                )
            },
        )
    try:
        yield
    finally:
        sched = getattr(container, "scheduler", None)
        if sched is not None:
            try:
                sched.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        # 以前从不停止 job queue → daemon 线程在测试/reload 场景里泄漏
        job_queue = getattr(container, "job_queue", None)
        if job_queue is not None:
            try:
                job_queue.stop()
            except Exception:  # noqa: BLE001
                pass


def create_app() -> FastAPI:
    settings = get_settings()

    # Fail-fast：无认证 + 可达网络的绑定 = 任何人都能读写全部记忆。
    # 这里主动拒绝启动，而不是只打一条容易被忽略的警告。
    problem = exposure_problem(
        host=settings.host,
        api_token=settings.api_token,
        admin_token=settings.admin_token,
        allow_insecure_public=settings.allow_insecure_public,
    )
    if problem is not None:
        raise RuntimeError(problem)

    # /docs、/redoc、/openapi.json 会暴露完整接口面；生产建议 ERAHERM_ENABLE_DOCS=false
    docs_kwargs = (
        {}
        if settings.enable_docs
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )
    app = FastAPI(
        title="EraHerm-Memory",
        version=__version__,
        description="Embeddable Agent memory kernel",
        lifespan=lifespan,
        **docs_kwargs,
    )
    app.add_middleware(RequestContextMiddleware)
    # 限流器必须是**进程级单例**：如果每次请求都新建，桶永远是满的、限流静默失效。
    app.add_middleware(
        RateLimitMiddleware,
        limiter=TokenBucketLimiter(
            per_minute=settings.rate_limit_per_minute,
            burst=settings.rate_limit_burst,
        ),
        enabled=settings.rate_limit_enabled,
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/demo/")

    demo_dir = Path(__file__).resolve().parent.parent / "demo"
    if settings.enable_demo and demo_dir.is_dir():
        app.mount("/demo", StaticFiles(directory=str(demo_dir), html=True), name="demo")

    return app


app = create_app()
