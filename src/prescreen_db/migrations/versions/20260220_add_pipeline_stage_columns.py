"""Create prescreen_sessions table with all columns.

This is the initial migration that creates the prescreen_sessions table.
It includes all columns from the ORM model, including the pipeline-stage
columns (pipeline_stage, llm_questions, llm_responses) that support the
PrescreenPipeline orchestrator.

Revision ID: 20260220_pipeline
Revises:
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID

# revision identifiers, used by Alembic.
revision = "20260220_pipeline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Create the prescreen_sessions table with all columns ---
    op.create_table(
        "prescreen_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # Identity
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text, nullable=False),
        # Lifecycle
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'created'"),
        ),
        sa.Column(
            "current_phase",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("ruleset_version", sa.Text, nullable=True),
        # Phase 0: Demographics
        sa.Column(
            "demographics",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Phase 2: Symptom selection (dedicated columns for query performance)
        sa.Column("primary_symptom", sa.Text, nullable=True),
        sa.Column("secondary_symptoms", ARRAY(sa.Text), nullable=True),
        # Phase 1/3/4: Question responses
        sa.Column(
            "responses",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Phase 3: ER flags
        sa.Column("er_flags", JSONB, nullable=True),
        # Termination
        sa.Column("terminated_at_phase", sa.SmallInteger, nullable=True),
        sa.Column("termination_reason", sa.Text, nullable=True),
        # Final result
        sa.Column("result", JSONB, nullable=True),
        # Pipeline stage (post-rule-based orchestration)
        sa.Column(
            "pipeline_stage",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'rule_based'"),
        ),
        # LLM Q&A
        sa.Column("llm_questions", JSONB, nullable=True),
        sa.Column("llm_responses", JSONB, nullable=True),
        # Timestamps
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
        # Table-level constraints
        sa.UniqueConstraint("user_id", "session_id", name="uq_user_session"),
        sa.CheckConstraint(
            "current_phase BETWEEN 0 AND 5", name="ck_phase_range"
        ),
        sa.CheckConstraint(
            "status != 'completed' OR result IS NOT NULL",
            name="ck_completed_has_result",
        ),
        sa.CheckConstraint(
            "status != 'terminated' OR terminated_at_phase IS NOT NULL",
            name="ck_terminated_has_phase",
        ),
    )

    # --- Indexes ---
    op.create_index("ix_user_id", "prescreen_sessions", ["user_id"])
    op.create_index("ix_status", "prescreen_sessions", ["status"])
    op.create_index("ix_pipeline_stage", "prescreen_sessions", ["pipeline_stage"])
    op.create_index(
        "ix_primary_symptom",
        "prescreen_sessions",
        ["primary_symptom"],
        postgresql_where=sa.text("primary_symptom IS NOT NULL"),
    )
    op.create_index(
        "ix_responses_gin",
        "prescreen_sessions",
        ["responses"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_demographics_gin",
        "prescreen_sessions",
        ["demographics"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_result_gin",
        "prescreen_sessions",
        ["result"],
        postgresql_using="gin",
        postgresql_where=sa.text("result IS NOT NULL"),
    )
    op.create_index(
        "ix_active_user_session",
        "prescreen_sessions",
        ["user_id", "session_id"],
        postgresql_where=sa.text("status IN ('created', 'in_progress')"),
    )


def downgrade() -> None:
    op.drop_table("prescreen_sessions")
