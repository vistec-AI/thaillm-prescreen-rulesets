"""FastAPI dependency injection — provides DB sessions, pipeline, store, and user identity.

Each request that touches the database gets a fresh ``AsyncSession`` via
``get_db()``.  The session is committed on success and rolled back on error,
matching the SDK convention where engine/repository call ``flush()`` but
never ``commit()``.
"""

import hmac
from typing import AsyncGenerator

from fastapi import Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_db.engine import get_session_factory
from prescreen_rulesets.pipeline import PrescreenPipeline
from prescreen_rulesets.ruleset import RulesetStore


# ------------------------------------------------------------------
# Database session — transaction boundary lives here
# ------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session; commit on success, rollback on error.

    The SDK's repository methods call ``flush()`` but never ``commit()``,
    so this dependency is the single place where transactions are finalised.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ------------------------------------------------------------------
# Pipeline & store — stashed on app.state during lifespan
# ------------------------------------------------------------------

def get_pipeline(request: Request) -> PrescreenPipeline:
    """Return the pipeline singleton from ``app.state``."""
    return request.app.state.pipeline


def get_store(request: Request) -> RulesetStore:
    """Return the RulesetStore singleton from ``app.state``."""
    return request.app.state.store


# ------------------------------------------------------------------
# User identity — extracted from the X-User-ID header
# ------------------------------------------------------------------

async def get_user_id(
    request: Request,
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    x_proxy_secret: str | None = Header(None, alias="X-Proxy-Secret"),
) -> str:
    """Extract user identity from the ``X-User-ID`` header.

    Returns 401 if the header is missing — every session endpoint
    requires a known caller.

    When ``TRUSTED_PROXY_SECRET`` is configured, the request must also
    carry a matching ``X-Proxy-Secret`` header.  This proves the
    ``X-User-ID`` was injected by a trusted API gateway and not forged
    by an external client.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-ID header is required")

    # --- Proxy-secret validation (opt-in via TRUSTED_PROXY_SECRET) ---
    expected_secret: str | None = request.app.state.settings.trusted_proxy_secret
    if expected_secret:
        if not x_proxy_secret:
            raise HTTPException(
                status_code=403,
                detail="X-Proxy-Secret header is required",
            )
        # Constant-time comparison to prevent timing side-channels.
        if not hmac.compare_digest(x_proxy_secret, expected_secret):
            raise HTTPException(status_code=403, detail="Invalid proxy secret")

    return x_user_id
