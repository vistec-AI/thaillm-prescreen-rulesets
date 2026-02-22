"""Admin endpoints — bulk cleanup and purge operations.

Protected by the ``ADMIN_API_KEY`` environment variable.  Every request
must include an ``X-Admin-Key`` header whose value matches the configured
key.  Returns 401 if missing, 403 if wrong.
"""

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_db.repository import SessionRepository

from prescreen_server.dependencies import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


# ------------------------------------------------------------------
# Auth dependency
# ------------------------------------------------------------------

async def require_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
) -> str:
    """Validate the ``X-Admin-Key`` header against ``ADMIN_API_KEY`` env var.

    Raises 401 if the header is missing, 403 if the env var is not set
    or the key does not match.
    """
    expected = os.getenv("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Admin endpoints are disabled (ADMIN_API_KEY not configured)",
        )
    if not x_admin_key:
        raise HTTPException(status_code=401, detail="X-Admin-Key header is required")
    if x_admin_key != expected:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key


# ------------------------------------------------------------------
# Response models
# ------------------------------------------------------------------

class CleanupResult(BaseModel):
    """Response body for cleanup operations."""
    affected_rows: int
    action: str


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

_repo = SessionRepository()


@router.post("/cleanup/sessions")
async def cleanup_sessions(
    older_than_days: int = Query(90, ge=0),
    status: list[str] | None = Query(None),
    hard: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
) -> CleanupResult:
    """Bulk soft-delete or hard-delete old sessions.

    Args:
        older_than_days: sessions older than this many days are affected
        status: filter by session status (e.g. ``completed``, ``terminated``)
        hard: if true, permanently DELETE rows; if false, set deleted_at
    """
    affected = await _repo.bulk_purge_old_sessions(
        db,
        older_than_days=older_than_days,
        status_filter=status,
        hard=hard,
    )
    action = "hard_delete" if hard else "soft_delete"
    return CleanupResult(affected_rows=affected, action=action)


@router.post("/cleanup/purge-deleted")
async def purge_deleted(
    older_than_days: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin_key),
) -> CleanupResult:
    """Permanently remove soft-deleted rows.

    Args:
        older_than_days: only purge rows soft-deleted more than this many
            days ago.  Default 0 purges all soft-deleted rows.
    """
    affected = await _repo.purge_soft_deleted(
        db,
        older_than_days=older_than_days,
    )
    return CleanupResult(affected_rows=affected, action="purge_soft_deleted")
