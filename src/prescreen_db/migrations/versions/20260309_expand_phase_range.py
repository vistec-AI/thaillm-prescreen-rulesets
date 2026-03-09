"""Expand phase range from 0-5 to 0-7 for 8-phase prescreening flow.

Adds two new phases between OLDCARTS (4) and OPD (now 7):
  - Phase 5: Past History (height, weight, medical conditions, pediatric questions)
  - Phase 6: Personal History (occupation, hometown, smoking, alcohol)

Also migrates in-flight sessions: any session at phase 5 (old OPD) is
moved to phase 7 (new OPD position).

Revision ID: 20260309_phase_range
Revises: 20260222_soft_delete
Create Date: 2026-03-09
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260309_phase_range"
down_revision = "20260222_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Migrate in-flight sessions from old phase 5 (OPD) to new phase 7 ---
    # Must happen BEFORE the constraint change to avoid constraint violations
    # on the intermediate state.
    op.execute(
        "UPDATE prescreen_sessions SET current_phase = 7 WHERE current_phase = 5"
    )

    # --- Update CHECK constraint to allow phases 0-7 ---
    op.drop_constraint("ck_phase_range", "prescreen_sessions")
    op.create_check_constraint(
        "ck_phase_range",
        "prescreen_sessions",
        "current_phase BETWEEN 0 AND 7",
    )


def downgrade() -> None:
    # --- Migrate sessions back from phase 7 to phase 5 ---
    op.execute(
        "UPDATE prescreen_sessions SET current_phase = 5 WHERE current_phase = 7"
    )
    # Clear any sessions stuck in phases 5/6 (new phases) back to phase 4
    op.execute(
        "UPDATE prescreen_sessions SET current_phase = 4 "
        "WHERE current_phase IN (5, 6)"
    )

    # --- Restore old CHECK constraint ---
    op.drop_constraint("ck_phase_range", "prescreen_sessions")
    op.create_check_constraint(
        "ck_phase_range",
        "prescreen_sessions",
        "current_phase BETWEEN 0 AND 5",
    )
