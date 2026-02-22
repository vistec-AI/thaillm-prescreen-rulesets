"""Application factory and CLI entry point.

``create_app()`` builds the FastAPI application with:
  - Lifespan handler that loads rulesets and initialises the pipeline once
  - CORS middleware
  - Global exception handlers (SDK ValueError → 404/409/400)
  - All API routes mounted under ``/api/v1``
  - A ``/health`` endpoint for readiness probes

The ``cli()`` function is the ``prescreen-server`` console-script entry point.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prescreen_db.engine import dispose_engine, get_engine
from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.pipeline import PrescreenPipeline
from prescreen_rulesets.ruleset import RulesetStore

from prescreen_server.config import ServerSettings, load_settings
from prescreen_server.errors import (
    generic_error_handler,
    key_error_handler,
    value_error_handler,
)
from prescreen_server.routes import register_routes

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Lifespan — runs once at startup/shutdown
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise shared resources at startup, tear down on shutdown.

    Startup:
      1. Load YAML rulesets into a ``RulesetStore``
      2. Build ``PrescreenEngine`` and ``PrescreenPipeline``
      3. Stash them on ``app.state`` for dependency injection

    Shutdown:
      1. Dispose the database engine's connection pool
    """
    settings: ServerSettings = app.state.settings

    # --- Load rulesets ---
    store = RulesetStore(ruleset_dir=settings.ruleset_dir)
    store.load()
    logger.info("RulesetStore loaded successfully")

    # --- Build pipeline ---
    engine = PrescreenEngine(store)
    pipeline = PrescreenPipeline(engine, store)

    app.state.store = store
    app.state.pipeline = pipeline

    yield

    # --- Shutdown ---
    await dispose_engine()
    logger.info("Database engine disposed")


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

def create_app(settings: ServerSettings | None = None) -> FastAPI:
    """Build and return the configured FastAPI application."""
    if settings is None:
        settings = load_settings()

    # --- Configure logging ---
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    app = FastAPI(
        title="Prescreen API Server",
        description="REST API for the ThaiLLM prescreening pipeline",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store settings so the lifespan handler can read them
    app.state.settings = settings

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers ---
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(KeyError, key_error_handler)
    app.add_exception_handler(Exception, generic_error_handler)

    # --- Health check (outside /api/v1 prefix) ---
    @app.get("/health")
    async def health() -> dict:
        """Readiness probe — verifies DB connectivity."""
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(
                    __import__("sqlalchemy").text("SELECT 1")
                )
            return {"status": "ok"}
        except Exception as exc:
            logger.error("Health check failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # --- Mount all API routes ---
    register_routes(app)

    return app


# ------------------------------------------------------------------
# Module-level ASGI export (for uvicorn prescreen_server.app:app)
# ------------------------------------------------------------------
app = create_app()


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def cli() -> None:
    """Console-script entry point: ``prescreen-server``."""
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "prescreen_server.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )
