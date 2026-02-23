"""LLM integration endpoints — submit LLM answers and get LLM prompts.

These endpoints handle the ``llm_questioning`` pipeline stage, where
LLM-generated follow-up questions are presented and answered before
the final prediction runs.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_rulesets.models.pipeline import LLMAnswer, PipelineResult
from prescreen_rulesets.pipeline import PrescreenPipeline

from prescreen_server.dependencies import get_db, get_pipeline, get_user_id

router = APIRouter(tags=["llm"])


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/sessions/{session_id}/llm-answers")
async def submit_llm_answers(
    session_id: str,
    body: list[LLMAnswer],
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> PipelineResult:
    """Submit answers to LLM-generated follow-up questions.

    Only valid during the ``llm_questioning`` pipeline stage.  Stores the
    answers, runs prediction (if available), and returns the final result.
    """
    return await pipeline.submit_llm_answers(
        db, user_id=user_id, session_id=session_id, answers=body,
    )


@router.get("/sessions/{session_id}/llm-prompt")
async def get_llm_prompt(
    session_id: str,
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> dict:
    """Render the current step as an LLM-ready prompt string.

    Returns ``{prompt: "..."}`` or ``{prompt: null}`` if there is
    nothing to prompt for (e.g. session is in the ``done`` stage).
    """
    prompt = await pipeline.get_llm_prompt(
        db, user_id=user_id, session_id=session_id,
    )
    return {"prompt": prompt}
