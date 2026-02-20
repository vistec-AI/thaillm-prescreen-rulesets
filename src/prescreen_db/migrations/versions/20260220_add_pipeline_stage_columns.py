"""Add pipeline_stage, llm_questions, llm_responses columns.

These columns support the PrescreenPipeline orchestrator that wraps
the rule-based engine with LLM question generation and prediction stages.

Revision ID: 20260220_pipeline
Revises:
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260220_pipeline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- pipeline_stage: tracks which macro-stage the session is in ---
    op.add_column(
        "prescreen_sessions",
        sa.Column(
            "pipeline_stage",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'rule_based'"),
        ),
    )
    op.create_index(
        "ix_pipeline_stage",
        "prescreen_sessions",
        ["pipeline_stage"],
    )

    # --- llm_questions: generated follow-up question strings ---
    op.add_column(
        "prescreen_sessions",
        sa.Column("llm_questions", JSONB, nullable=True),
    )

    # --- llm_responses: LLM Q&A pairs ---
    op.add_column(
        "prescreen_sessions",
        sa.Column("llm_responses", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prescreen_sessions", "llm_responses")
    op.drop_column("prescreen_sessions", "llm_questions")
    op.drop_index("ix_pipeline_stage", table_name="prescreen_sessions")
    op.drop_column("prescreen_sessions", "pipeline_stage")
