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
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
# Backend selection — pick the LLM connectors at startup
# ------------------------------------------------------------------
# Two env vars choose which connectors the pipeline uses:
#   PREDICTOR_BACKEND          — "openai" | "medgemma". Never null: defaults
#                                to "openai" so existing deployments are
#                                unaffected. A predictor is always required.
#   QUESTION_GENERATOR_BACKEND — "openai" | "" (empty/unset → "openai").
#                                May be null: an explicitly empty value (or
#                                the legacy SKIP_GENERATOR=true flag) disables
#                                LLM question generation entirely.

def _build_predictor(store: RulesetStore):
    """Construct the prediction module selected by ``PREDICTOR_BACKEND``.

    Always returns a predictor — the pipeline cannot run without one.  Raises
    ``RuntimeError`` for an unrecognised backend name so misconfiguration fails
    fast at startup rather than on the first prediction call.
    """
    backend = (
        os.environ.get("PREDICTOR_BACKEND", "openai").strip().lower() or "openai"
    )
    if backend == "openai":
        from prescreen_rulesets.prediction import OpenAIPredictionModule
        logger.info("Prediction backend: OpenAIPredictionModule")
        return OpenAIPredictionModule(store=store)
    if backend == "medgemma":
        from prescreen_rulesets.prediction import MedgemmaPredictionModule
        logger.info("Prediction backend: MedgemmaPredictionModule")
        return MedgemmaPredictionModule(store=store)
    raise RuntimeError(
        f"Unknown PREDICTOR_BACKEND={backend!r}. Valid values: openai, medgemma."
    )


def _build_generator():
    """Construct the question generator selected by ``QUESTION_GENERATOR_BACKEND``.

    Returns ``None`` when question generation is disabled — either by an
    explicitly empty ``QUESTION_GENERATOR_BACKEND`` or by the legacy
    ``SKIP_GENERATOR=true`` flag (still honoured for back-compat).  An unset
    variable defaults to ``"openai"`` so the generator stays enabled by default.
    Raises ``RuntimeError`` for an unrecognised non-empty backend name.
    """
    if os.environ.get("SKIP_GENERATOR", "").lower() == "true":
        logger.warning("SKIP_GENERATOR=true — question generator disabled")
        return None
    backend = os.environ.get(
        "QUESTION_GENERATOR_BACKEND", "openai",
    ).strip().lower()
    if not backend:
        logger.warning(
            "QUESTION_GENERATOR_BACKEND is empty — question generator disabled"
        )
        return None
    if backend == "openai":
        from prescreen_rulesets.question_generator import OpenAIQuestionGenerator
        logger.info("Question generator backend: OpenAIQuestionGenerator")
        return OpenAIQuestionGenerator()
    raise RuntimeError(
        f"Unknown QUESTION_GENERATOR_BACKEND={backend!r}. "
        "Valid values: openai (or empty to disable)."
    )


def _openai_backend_selected() -> bool:
    """True when any selected backend is OpenAI-based and so needs an API key.

    The OpenAI connectors require ``OPENAI_API_KEY`` or ``OPENROUTER_API_KEY``;
    the medgemma connector reads its own ``VLLM_*`` config and needs neither.
    """
    predictor = (
        os.environ.get("PREDICTOR_BACKEND", "openai").strip().lower() or "openai"
    )
    if predictor == "openai":
        return True
    # Predictor is not OpenAI — the key is only needed if the generator is.
    if os.environ.get("SKIP_GENERATOR", "").lower() == "true":
        return False
    generator = os.environ.get(
        "QUESTION_GENERATOR_BACKEND", "openai",
    ).strip().lower()
    return generator == "openai"


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

    # --- Build pipeline (prediction required; question generation optional) ---
    engine = PrescreenEngine(store)

    # The OpenAI-backed connectors need an API key; the medgemma connector
    # reads its own VLLM_* config, so only validate the key when an OpenAI
    # backend is actually selected.
    if _openai_backend_selected() and not (
        os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    ):
        raise RuntimeError(
            "No LLM API key configured. Set OPENAI_API_KEY or "
            "OPENROUTER_API_KEY environment variable. "
            "An OpenAI-backed prediction or question-generation backend is "
            "selected and requires an API key."
        )

    # Backend selection: PREDICTOR_BACKEND (required) + QUESTION_GENERATOR_BACKEND
    # (optional — None disables LLM question generation).
    predictor = _build_predictor(store)
    generator = _build_generator()

    pipeline = PrescreenPipeline(engine, store, generator=generator, predictor=predictor)

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

    # --- OpenAPI tag metadata for Swagger UI grouping ---
    openapi_tags = [
        {"name": "sessions", "description": "Session lifecycle — create, get, list"},
        {"name": "steps", "description": "Step interaction — get current step, submit answers"},
        {"name": "llm", "description": "LLM integration — submit LLM answers, get prompts"},
        {"name": "reference", "description": "Read-only reference data (departments, symptoms, etc.)"},
        {"name": "admin", "description": "Admin-only bulk cleanup and purge operations (requires X-Admin-Key)"},
    ]

    app = FastAPI(
        title="Prescreen API Server",
        description=(
            "REST API for the ThaiLLM prescreening pipeline.\n\n"
            "See the [Developer Guide](/guide/) for narrative documentation, "
            "flow walkthroughs, and deployment instructions."
        ),
        version="0.1.0",
        lifespan=lifespan,
        openapi_tags=openapi_tags,
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
            # Log the full exception server-side but return a generic
            # message to the client to avoid leaking DB connection
            # strings or internal topology details.
            logger.error("Health check failed: %s", exc)
            return {"status": "error", "detail": "Database connection failed"}

    # --- Mount all API routes ---
    register_routes(app)

    # --- Developer guide (MkDocs-built static site) ---
    # Served at /guide/ when docs_site/ exists.  html=True makes directory
    # URLs resolve to index.html.  The guard means the server starts even
    # if the docs haven't been built yet.
    docs_site = Path(__file__).parent / "docs_site"
    if docs_site.exists():
        app.mount("/guide", StaticFiles(directory=str(docs_site), html=True), name="guide")

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
