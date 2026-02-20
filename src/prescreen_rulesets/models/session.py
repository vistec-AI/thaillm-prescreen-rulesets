"""Session and step models — the contract between the engine and API callers.

These models define what the engine returns at each step of the prescreening flow.
They are intentionally decoupled from the ORM models in ``prescreen_db`` so that
API consumers never see database internals.

Step types:
  - QuestionsStep: present one or more questions to the user
  - TerminationStep: session ended with a result (terminated or completed)

The ``StepResult`` union covers both cases so callers can dispatch on ``type``.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class QuestionPayload(BaseModel):
    """Flattened question for API consumers.

    Strips internal action/routing details and presents only what the UI
    needs to render the question.  The engine converts typed Question models
    into this flat representation.
    """

    qid: str
    question: str
    question_type: str
    # [{id, label}] for single_select/multi_select/image_* types
    options: list[dict] | None = None
    # [{id, label, kind}] for free_text_with_fields
    fields: list[dict] | None = None
    # {min, max, step, default} for number_range
    constraints: dict | None = None
    # Image URL/path for image_* types
    image: str | None = None
    # Extra context (e.g. symptom grouping for ER checklist)
    metadata: dict | None = None


class QuestionsStep(BaseModel):
    """Engine step: present questions to the user and wait for answers."""

    type: Literal["questions"] = "questions"
    phase: int
    phase_name: str
    questions: list[QuestionPayload]


class TerminationStep(BaseModel):
    """Engine step: session ended with a result.

    ``type`` is "terminated" for early exits (e.g. ER redirect) or "completed"
    for sessions that finished all phases normally.
    """

    type: Literal["terminated", "completed"]
    phase: int
    departments: list[dict]
    severity: dict | None = None
    reason: str | None = None


# Callers can match on step.type to dispatch rendering logic.
StepResult = QuestionsStep | TerminationStep


class SessionInfo(BaseModel):
    """Public view of session state for API consumers.

    Maps from the ORM ``PrescreenSession`` model but exposes only what
    external callers need.
    """

    user_id: str
    session_id: str
    status: str
    current_phase: int
    created_at: datetime
    updated_at: datetime
