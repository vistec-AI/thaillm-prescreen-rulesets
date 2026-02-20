"""Database-level enumerations for prescreen sessions."""

import enum


class SessionStatus(str, enum.Enum):
    """Lifecycle states for a prescreen session.

    Transitions:
        created -> in_progress  (first question answered)
        in_progress -> completed (all phases done, result written)
        in_progress -> terminated (early exit, e.g. ER redirect)
    """

    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    TERMINATED = "terminated"


class PipelineStage(str, enum.Enum):
    """Macro-stage of the full prescreening pipeline.

    The pipeline wraps the rule-based engine and adds LLM questioning +
    prediction stages.  This enum tracks which macro-stage the session is in.

    Transitions:
        rule_based -> llm_questioning  (engine done, LLM questions generated)
        rule_based -> done             (early termination or no generator/predictor)
        llm_questioning -> done        (LLM answers submitted, prediction complete)
    """

    RULE_BASED = "rule_based"
    LLM_QUESTIONING = "llm_questioning"
    DONE = "done"
