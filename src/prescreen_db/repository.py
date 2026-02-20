"""Async CRUD repository for PrescreenSession.

All public methods accept an ``AsyncSession`` so the caller controls
transaction boundaries (useful for composing multiple writes in the SDK).

The repository deliberately avoids business-logic validation — that belongs
in the SDK layer.  It *does* enforce structural invariants (e.g. a completed
session must have a result) via DB constraints.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_db.models.enums import SessionStatus
from prescreen_db.models.session import PrescreenSession


class SessionRepository:
    """Async read/write operations on the ``prescreen_sessions`` table."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_session(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        ruleset_version: str | None = None,
    ) -> PrescreenSession:
        """Insert a new session row and return it.

        The caller must ``await db.commit()`` to persist.
        """
        session = PrescreenSession(
            user_id=user_id,
            session_id=session_id,
            ruleset_version=ruleset_version,
        )
        db.add(session)
        await db.flush()  # Populate server-side defaults (id, timestamps)
        return session

    # ------------------------------------------------------------------
    # Read — single row
    # ------------------------------------------------------------------

    async def get_by_id(
        self, db: AsyncSession, session_pk: uuid.UUID
    ) -> PrescreenSession | None:
        """Fetch a session by its primary-key UUID."""
        return await db.get(PrescreenSession, session_pk)

    async def get_by_user_and_session(
        self, db: AsyncSession, user_id: str, session_id: str
    ) -> PrescreenSession | None:
        """Fetch a session by the unique (user_id, session_id) pair."""
        stmt = select(PrescreenSession).where(
            PrescreenSession.user_id == user_id,
            PrescreenSession.session_id == session_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_session(
        self, db: AsyncSession, user_id: str
    ) -> PrescreenSession | None:
        """Return the user's currently active session, if any.

        "Active" means status is ``created`` or ``in_progress``.  If more
        than one exists (shouldn't happen), the most recently created one
        is returned.
        """
        stmt = (
            select(PrescreenSession)
            .where(
                PrescreenSession.user_id == user_id,
                PrescreenSession.status.in_(
                    [SessionStatus.CREATED, SessionStatus.IN_PROGRESS]
                ),
            )
            .order_by(PrescreenSession.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Read — multiple rows
    # ------------------------------------------------------------------

    async def list_by_user(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[PrescreenSession]:
        """List sessions for a user, most recent first."""
        stmt = (
            select(PrescreenSession)
            .where(PrescreenSession.user_id == user_id)
            .order_by(PrescreenSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Update — phase data
    # ------------------------------------------------------------------

    async def save_demographics(
        self, db: AsyncSession, session: PrescreenSession, demographics: dict[str, Any]
    ) -> PrescreenSession:
        """Merge demographics dict into the session's demographics JSONB.

        Uses Python-side merge so the caller can see the new value
        immediately.  The DB-level ``||`` merge happens on flush.
        """
        merged = {**session.demographics, **demographics}
        session.demographics = merged
        session.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return session

    async def record_response(
        self,
        db: AsyncSession,
        session: PrescreenSession,
        qid: str,
        value: Any,
    ) -> PrescreenSession:
        """Record a single question response keyed by ``qid``.

        Each entry stores the answer value and a timestamp so we can
        replay the session in order.
        """
        entry = {
            "value": value,
            "answered_at": datetime.now(timezone.utc).isoformat(),
        }
        # Shallow-copy to ensure SQLAlchemy detects the mutation
        updated = {**session.responses, qid: entry}
        session.responses = updated
        session.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return session

    async def save_symptom_selection(
        self,
        db: AsyncSession,
        session: PrescreenSession,
        *,
        primary_symptom: str,
        secondary_symptoms: list[str] | None = None,
    ) -> PrescreenSession:
        """Save the Phase 2 symptom selection."""
        session.primary_symptom = primary_symptom
        session.secondary_symptoms = secondary_symptoms
        session.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return session

    async def advance_phase(
        self, db: AsyncSession, session: PrescreenSession, next_phase: int
    ) -> PrescreenSession:
        """Move the session to the next phase.

        Also transitions status from ``created`` to ``in_progress`` on the
        first advance (phase 0 -> 1).
        """
        session.current_phase = next_phase
        if session.status == SessionStatus.CREATED:
            session.status = SessionStatus.IN_PROGRESS
        session.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return session

    async def save_er_flags(
        self,
        db: AsyncSession,
        session: PrescreenSession,
        er_flags: dict[str, Any],
    ) -> PrescreenSession:
        """Save Phase 3 ER checklist flags."""
        session.er_flags = er_flags
        session.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return session

    # ------------------------------------------------------------------
    # Update — terminal states
    # ------------------------------------------------------------------

    async def terminate_session(
        self,
        db: AsyncSession,
        session: PrescreenSession,
        *,
        phase: int,
        reason: str,
    ) -> PrescreenSession:
        """Mark a session as terminated (e.g. ER redirect).

        The CHECK constraint ``ck_terminated_has_phase`` enforces that
        ``terminated_at_phase`` is non-null whenever status is terminated.
        """
        now = datetime.now(timezone.utc)
        session.status = SessionStatus.TERMINATED
        session.terminated_at_phase = phase
        session.termination_reason = reason
        session.completed_at = now
        session.updated_at = now
        await db.flush()
        return session

    async def complete_session(
        self,
        db: AsyncSession,
        session: PrescreenSession,
        result: dict[str, Any],
    ) -> PrescreenSession:
        """Mark a session as successfully completed with a result payload.

        The CHECK constraint ``ck_completed_has_result`` enforces that
        ``result`` is non-null whenever status is completed.
        """
        now = datetime.now(timezone.utc)
        session.status = SessionStatus.COMPLETED
        session.result = result
        session.completed_at = now
        session.updated_at = now
        await db.flush()
        return session
