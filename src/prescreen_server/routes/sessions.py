"""Session management endpoints — create, get, list sessions.

All endpoints require the ``X-User-ID`` header for user identification.
Session identity is the (user_id, session_id) pair, enforced by a unique
constraint in the database.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_rulesets.models.session import SessionInfo
from prescreen_rulesets.pipeline import PrescreenPipeline

from prescreen_server.config import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from prescreen_server.dependencies import get_db, get_pipeline, get_user_id

router = APIRouter(tags=["sessions"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    """Body for POST /sessions."""
    session_id: str
    ruleset_version: str | None = None


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/sessions", status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> SessionInfo:
    """Create a new prescreening session.

    Returns 201 on success.  Raises 409 if a session with the same
    (user_id, session_id) already exists.
    """
    return await pipeline.create_session(
        db,
        user_id=user_id,
        session_id=body.session_id,
        ruleset_version=body.ruleset_version,
    )


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> SessionInfo:
    """Get session info by session_id.

    Raises 404 if the session does not exist for this user.
    """
    info = await pipeline.get_session(
        db, user_id=user_id, session_id=session_id,
    )
    if info is None:
        raise ValueError(f"Session not found: session_id={session_id}")
    return info


@router.delete("/sessions/{session_id}", status_code=204)
async def soft_delete_session(
    session_id: str,
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> None:
    """Soft-delete a session.

    The session row is retained but excluded from all normal queries.
    Returns 204 on success, 404 if the session does not exist.
    """
    await pipeline.soft_delete_session(
        db, user_id=user_id, session_id=session_id,
    )


@router.delete("/sessions/{session_id}/permanent", status_code=204)
async def hard_delete_session(
    session_id: str,
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> None:
    """Permanently delete a session (irreversible, GDPR erasure).

    The session row is removed from the database entirely.
    Returns 204 on success, 404 if the session does not exist.
    """
    await pipeline.hard_delete_session(
        db, user_id=user_id, session_id=session_id,
    )


@router.get("/sessions")
async def list_sessions(
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[SessionInfo]:
    """List sessions for the current user, most recent first."""
    return await pipeline.list_sessions(
        db, user_id=user_id, limit=limit, offset=offset,
    )
