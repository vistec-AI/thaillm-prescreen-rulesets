"""Add disable_early_termination flag and skipped_terminations log.

When ``disable_early_termination`` is True, the engine skips all early
termination points (ER critical, ER checklist, OLDCARTS/OPD terminate
actions) and continues through all 8 phases.  Would-be terminations are
recorded in the ``skipped_terminations`` JSONB list for analysis.

Revision ID: 20260325_disable_early_term
Revises: 20260309_phase_range
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260325_disable_early_term"
down_revision = "20260309_phase_range"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Boolean flag — default False so existing sessions are unaffected.
    op.add_column(
        "prescreen_sessions",
        sa.Column(
            "disable_early_termination",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # JSONB list of skipped termination events (nullable — NULL means none).
    op.add_column(
        "prescreen_sessions",
        sa.Column("skipped_terminations", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prescreen_sessions", "skipped_terminations")
    op.drop_column("prescreen_sessions", "disable_early_termination")
