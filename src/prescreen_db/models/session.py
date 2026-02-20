"""PrescreenSession ORM model — single row per user session.

Each row tracks one complete prescreening flow (phases 0-5).  Heavy use of
JSONB columns avoids JOINs: the SDK can fetch a single row and replay the
entire session without touching other tables.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from prescreen_db.models.base import Base
from prescreen_db.models.enums import PipelineStage, SessionStatus


class PrescreenSession(Base):
    """One row per prescreen session.

    A user may have many sessions over time; each is uniquely identified
    by the (user_id, session_id) pair.
    """

    __tablename__ = "prescreen_sessions"

    # --- Primary key ---
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # --- Identity ---
    # External user ID (e.g. LINE UID, HN, etc.)
    user_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # Caller-supplied session identifier, unique within a user
    session_id: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Lifecycle ---
    status: Mapped[SessionStatus] = mapped_column(
        # Store as the lowercase string value, not the Python name
        String(20),
        nullable=False,
        default=SessionStatus.CREATED,
        index=True,
    )
    # Which phase (0-5) the user is currently on
    current_phase: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # Ruleset version tag so we can trace which rules drove the session
    ruleset_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Phase 0: Demographics ---
    # Stored as a flat dict: {"dob": "...", "gender": "...", "height": ..., ...}
    demographics: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # --- Phase 2: Symptom selection ---
    # Dedicated columns (not inside JSONB) because they are frequently used
    # for filtering and routing lookups.
    primary_symptom: Mapped[str | None] = mapped_column(Text, nullable=True)
    secondary_symptoms: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )

    # --- Phase 1/3/4: Question responses ---
    # Dict keyed by qid -> {"value": ..., "answered_at": "ISO8601"}
    responses: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # --- Phase 3: ER flags ---
    # List of ER checklist items that the patient answered "yes" to.
    # Null means the phase hasn't been reached yet.
    er_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Termination ---
    # If the session was terminated early (e.g. ER redirect), record which
    # phase it happened in and why.
    terminated_at_phase: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True
    )
    termination_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Final result ---
    # Written once when status transitions to "completed".
    # Shape: {"departments": [...], "severity": "...", ...}
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Pipeline stage (post-rule-based orchestration) ---
    # Tracks which macro-stage of the full pipeline the session is in:
    # rule_based → llm_questioning → done.
    # server_default ensures existing rows get 'rule_based' without data migration.
    pipeline_stage: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PipelineStage.RULE_BASED,
        server_default=text("'rule_based'"),
    )

    # --- LLM Q&A (populated after rule-based phase completes) ---
    # Generated follow-up question strings: ["q1", "q2", ...]
    llm_questions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # LLM Q&A pairs: [{"question": "...", "answer": "..."}, ...]
    llm_responses: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # --- Table-level constraints ---
    __table_args__ = (
        # A user can only have one session with a given session_id
        UniqueConstraint("user_id", "session_id", name="uq_user_session"),
        # Phase must be between 0 and 5 (the 6 prescreening phases)
        CheckConstraint(
            "current_phase BETWEEN 0 AND 5",
            name="ck_phase_range",
        ),
        # Completed sessions must have a result payload
        CheckConstraint(
            "status != 'completed' OR result IS NOT NULL",
            name="ck_completed_has_result",
        ),
        # Terminated sessions must record which phase they stopped at
        CheckConstraint(
            "status != 'terminated' OR terminated_at_phase IS NOT NULL",
            name="ck_terminated_has_phase",
        ),
        # --- Indexes ---
        # B-tree on pipeline_stage for filtering sessions by macro-stage
        Index("ix_pipeline_stage", "pipeline_stage"),
        # B-tree on primary_symptom for routing lookups (only non-null rows)
        Index(
            "ix_primary_symptom",
            "primary_symptom",
            postgresql_where=text("primary_symptom IS NOT NULL"),
        ),
        # GIN indexes for JSONB path lookups (inspector queries, phase eval)
        Index("ix_responses_gin", "responses", postgresql_using="gin"),
        Index("ix_demographics_gin", "demographics", postgresql_using="gin"),
        Index(
            "ix_result_gin",
            "result",
            postgresql_using="gin",
            postgresql_where=text("result IS NOT NULL"),
        ),
        # Partial unique index: at most one active session per user.
        # "Active" means status is either 'created' or 'in_progress'.
        Index(
            "ix_active_user_session",
            "user_id",
            "session_id",
            postgresql_where=text("status IN ('created', 'in_progress')"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PrescreenSession(id={self.id!s}, user={self.user_id!r}, "
            f"session={self.session_id!r}, status={self.status!r}, "
            f"phase={self.current_phase})>"
        )
