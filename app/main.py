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
from app.container import build_container
from app.observability.middleware import RequestContextMiddleware


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
    try:
        yield
    finally:
        sched = getattr(container, "scheduler", None)
        if sched is not None:
            try:
                sched.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="EraHerm-Memory",
        version=__version__,
        description="Embeddable Agent memory kernel",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/demo/")

    demo_dir = Path(__file__).resolve().parent.parent / "demo"
    if demo_dir.is_dir():
        app.mount("/demo", StaticFiles(directory=str(demo_dir), html=True), name="demo")

    return app


app = create_app()
