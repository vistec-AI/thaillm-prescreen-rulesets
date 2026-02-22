"""Route registration — mounts all routers under ``/api/v1``."""

from fastapi import FastAPI

from prescreen_server.routes.admin import router as admin_router
from prescreen_server.routes.history import router as history_router
from prescreen_server.routes.llm import router as llm_router
from prescreen_server.routes.reference import router as reference_router
from prescreen_server.routes.sessions import router as sessions_router
from prescreen_server.routes.steps import router as steps_router

API_PREFIX = "/api/v1"


def register_routes(app: FastAPI) -> None:
    """Include all sub-routers under the versioned API prefix."""
    app.include_router(sessions_router, prefix=API_PREFIX)
    app.include_router(steps_router, prefix=API_PREFIX)
    app.include_router(llm_router, prefix=API_PREFIX)
    app.include_router(history_router, prefix=API_PREFIX)
    app.include_router(reference_router, prefix=API_PREFIX)
    app.include_router(admin_router, prefix=API_PREFIX)
