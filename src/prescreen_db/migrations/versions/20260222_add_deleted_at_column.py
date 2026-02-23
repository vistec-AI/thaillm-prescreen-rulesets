"""Add deleted_at column for soft-delete support.

Adds a nullable ``deleted_at`` timestamp column to ``prescreen_sessions``.
Rows with ``deleted_at IS NULL`` are considered live; non-null means
soft-deleted.

Also adds partial indexes to accelerate:
  - listing/querying non-deleted sessions (hot path)
  - TTL purge queries on soft-deleted rows

Updates the ``ix_active_user_session`` partial index to also exclude
soft-deleted rows, ensuring the "at most one active session per user"
invariant ignores soft-deleted sessions.

Revision ID: 20260222_soft_delete
Revises: 20260220_pipeline
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

# revision identifiers, used by Alembic.
revision = "20260222_soft_delete"
down_revision = "20260220_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Add the deleted_at column ---
    op.add_column(
        "prescreen_sessions",
        sa.Column("deleted_at", TIMESTAMP(timezone=True), nullable=True),
    )

    # --- Partial index: accelerate queries on non-deleted sessions ---
    # Covers the hot path: list/get sessions WHERE deleted_at IS NULL
    op.create_index(
        "ix_not_deleted_user",
        "prescreen_sessions",
        ["user_id", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # --- Partial index: accelerate TTL purge of soft-deleted rows ---
    op.create_index(
        "ix_deleted_at",
        "prescreen_sessions",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )

    # --- Update ix_active_user_session to also exclude soft-deleted rows ---
    # Drop the old index and recreate with the additional condition.
    op.drop_index("ix_active_user_session", table_name="prescreen_sessions")
    op.create_index(
        "ix_active_user_session",
        "prescreen_sessions",
        ["user_id", "session_id"],
        postgresql_where=sa.text(
            "status IN ('created', 'in_progress') AND deleted_at IS NULL"
        ),
    )


def downgrade() -> None:
    # Restore original ix_active_user_session (without deleted_at condition)
    op.drop_index("ix_active_user_session", table_name="prescreen_sessions")
    op.create_index(
        "ix_active_user_session",
        "prescreen_sessions",
        ["user_id", "session_id"],
        postgresql_where=sa.text("status IN ('created', 'in_progress')"),
    )

    op.drop_index("ix_deleted_at", table_name="prescreen_sessions")
    op.drop_index("ix_not_deleted_user", table_name="prescreen_sessions")
    op.drop_column("prescreen_sessions", "deleted_at")
