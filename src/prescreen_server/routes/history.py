"""Session history endpoint — retrieve the full Q&A trail.

Returns the chronological list of all questions and answers for a session,
including both rule-based phases (0-5) and LLM follow-up Q&A.  Works at
any point during the session — returns whatever has been answered so far.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from prescreen_rulesets.models.pipeline import QAPair
from prescreen_rulesets.pipeline import PrescreenPipeline

from prescreen_server.dependencies import get_db, get_pipeline, get_user_id

router = APIRouter(tags=["history"])


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    user_id: str = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
    pipeline: PrescreenPipeline = Depends(get_pipeline),
) -> list[QAPair]:
    """Return the full Q&A history for a session.

    Each entry contains ``qid``, ``question_type``, ``question`` (text),
    ``answer``, ``phase``, and ``source`` (``rule_based`` or ``llm_generated``).

    Can be called at any point — mid-session or after completion — to inspect
    what has been answered so far.
    """
    return await pipeline.get_history(
        db, user_id=user_id, session_id=session_id,
    )
