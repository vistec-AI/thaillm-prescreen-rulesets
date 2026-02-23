"""Step endpoints — get current step and submit answers.

These endpoints drive the rule-based prescreening flow.  The pipeline
dispatches by ``pipeline_stage``:
  - ``rule_based``: questions come from the PrescreenEngine
  - ``llm_questioning``: returns stored LLM questions
  - ``done``: returns the cached pipeline result

``submit_answer`` is only valid during the ``rule_based`` stage.
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_rulesets.models.pipeline import PipelineStep
from prescreen_rulesets.pipeline import PrescreenPipeline

from prescreen_server.dependencies import get_db, get_pipeline, get_user_id

router = APIRouter(tags=["steps"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SubmitAnswerRequest(BaseModel):
    """Body for POST /sessions/{session_id}/step.

    ``qid`` is optional — for bulk phases (0-3) it is ignored, and for
    sequential phases (4-5) the engine auto-derives it when ``None``.
    """
    qid: str | None = None
    value: Any


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/sessions/{session_id}/step")
async def get_current_step(
    session_id: str,
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> PipelineStep:
    """Return the current step for the session.

    The response shape depends on the pipeline stage:
      - ``questions``: rule-based questions to answer
      - ``llm_questions``: LLM-generated follow-up questions
      - ``pipeline_result``: final result with DDx/department/severity
    """
    return await pipeline.get_current_step(
        db, user_id=user_id, session_id=session_id,
    )


@router.post("/sessions/{session_id}/step")
async def submit_answer(
    session_id: str,
    body: SubmitAnswerRequest,
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> PipelineStep:
    """Submit an answer and advance the session.

    Only valid during the ``rule_based`` pipeline stage.  Returns the
    next step (which may be another ``questions`` step, ``llm_questions``,
    or the final ``pipeline_result``).
    """
    return await pipeline.submit_answer(
        db,
        user_id=user_id,
        session_id=session_id,
        qid=body.qid,
        value=body.value,
    )
