"""Comprehensive step_back tests — verifies going-back-one-step behaviour
across all 6 phases, including conditional/auto-evaluated question skipping.

Tests the contract documented in the flow-walkthrough:

  | Current state                        | Goes back to                                     |
  |--------------------------------------|--------------------------------------------------|
  | Phase 0                              | Error — already at first step (400)               |
  | Phase 1                              | Phase 0 (Demographics)                            |
  | Phase 2                              | Phase 1 (ER Critical)                             |
  | Phase 3                              | Phase 2 (Symptom Selection)                       |
  | Phase 4, has answered questions      | Last answered OLDCARTS question                   |
  | Phase 4, no answered questions       | Phase 3 (ER Checklist)                            |
  | Phase 5, has answered OPD questions  | Last answered OPD question                        |
  | Phase 5, no OPD answers              | Last answered OLDCARTS question (or Phase 3)      |
  | Phase 5, no OPD or OLDCARTS answers  | Phase 3                                           |

Additionally verifies:
  - After step_back, re-submitting the same answer advances normally
  - Conditional/gender_filter/age_filter questions are auto-resolved when
    navigating back — the user never sees them
  - Multiple consecutive step_back calls work correctly
  - Previous values are injected into bulk-phase question metadata
"""

from unittest.mock import AsyncMock

import pytest

from prescreen_db.models.enums import SessionStatus
from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.models.session import QuestionsStep, TerminationStep
from prescreen_rulesets.ruleset import RulesetStore

# Reuse mock infrastructure from test_engine
from test_engine import MockRepository, MockSessionRow, VALID_DEMOGRAPHICS

# Auto-evaluated question types — these should never be presented to the user
AUTO_EVAL_TYPES = {"gender_filter", "age_filter", "conditional"}


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture(scope="session")
def store():
    """Load the full RulesetStore once for the entire test session."""
    s = RulesetStore()
    s.load()
    return s


@pytest.fixture
def mock_repo():
    """Fresh MockRepository for each test."""
    return MockRepository()


@pytest.fixture
def engine(store, mock_repo):
    """PrescreenEngine with mocked repository."""
    eng = PrescreenEngine(store)
    eng._repo = mock_repo
    return eng


@pytest.fixture
def mock_db():
    """AsyncMock standing in for AsyncSession — flush/commit are no-ops."""
    return AsyncMock()


# =====================================================================
# Helpers
# =====================================================================


def _pick_answer(q):
    """Pick a deterministic valid answer for a QuestionPayload.

    Selects the first option for select types, middle value for
    number_range, and a placeholder string for free text.
    """
    qtype = q.question_type
    if qtype in ("single_select", "image_single_select"):
        return q.options[0]["id"] if q.options else "unknown"
    if qtype in ("multi_select", "image_multi_select"):
        return [q.options[0]["id"]] if q.options else []
    if qtype == "number_range":
        c = q.constraints or {}
        return (c.get("min", 0) + c.get("max", 10)) / 2
    if qtype == "free_text_with_fields":
        if q.fields:
            return {f["id"]: "ไม่มี" for f in q.fields}
        return "ไม่มี"
    # free_text and fallback
    return "ไม่มี"


def _pick_answer_last(q):
    """Pick the *last* option — avoids early-terminate branches.

    Some OPD decision trees terminate immediately on the first option
    (e.g. Wound's "yes, within 24h" → terminate).  Picking the last
    option navigates the non-terminating branch so more user-facing
    questions are reachable.
    """
    qtype = q.question_type
    if qtype in ("single_select", "image_single_select"):
        return q.options[-1]["id"] if q.options else "unknown"
    if qtype in ("multi_select", "image_multi_select"):
        return [q.options[-1]["id"]] if q.options else []
    if qtype == "number_range":
        c = q.constraints or {}
        # Use min value to stay below severity thresholds
        return c.get("min", 0)
    if qtype == "free_text_with_fields":
        if q.fields:
            return {f["id"]: "ไม่มี" for f in q.fields}
        return "ไม่มี"
    return "ไม่มี"


async def _advance_to_phase(
    engine, mock_db, target_phase: int, symptom="Headache", picker=None,
):
    """Create a session and advance it through all phases up to target_phase.

    Args:
        picker: answer-picking function. Defaults to ``_pick_answer``
            (first option).  Use ``_pick_answer_last`` to avoid
            early-terminate branches in OPD.

    Returns the step at the target phase.
    """
    if picker is None:
        picker = _pick_answer
    store = engine._store

    await engine.create_session(mock_db, user_id="u1", session_id="s1")
    if target_phase == 0:
        return await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )

    # Phase 0 → 1: submit demographics
    step = await engine.submit_answer(
        mock_db, user_id="u1", session_id="s1",
        value=VALID_DEMOGRAPHICS,
    )
    if target_phase == 1:
        return step

    # Phase 1 → 2: all-negative ER critical
    er_responses = {item.qid: False for item in store.er_critical}
    step = await engine.submit_answer(
        mock_db, user_id="u1", session_id="s1",
        qid="er_critical", value=er_responses,
    )
    if target_phase == 2:
        return step

    # Phase 2 → 3: symptom selection
    step = await engine.submit_answer(
        mock_db, user_id="u1", session_id="s1",
        qid="symptoms",
        value={"primary_symptom": symptom},
    )
    if target_phase == 3:
        return step

    # Phase 3 → 4: all-negative ER checklist
    checklist_items = store.get_er_checklist(symptom, pediatric=False)
    checklist_responses = {item.qid: False for item in checklist_items}
    step = await engine.submit_answer(
        mock_db, user_id="u1", session_id="s1",
        qid="er_checklist", value=checklist_responses,
    )
    if target_phase == 4:
        return step

    # Phase 4 → 5: answer all OLDCARTS questions until we reach phase 5
    max_iterations = 200  # safety limit
    for _ in range(max_iterations):
        if not isinstance(step, QuestionsStep):
            break
        if step.phase == 5:
            return step
        q = step.questions[0]
        answer = picker(q)
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=answer,
        )

    if target_phase == 5 and isinstance(step, QuestionsStep) and step.phase == 5:
        return step

    # If we couldn't reach phase 5, return whatever we got
    return step


async def _answer_sequential_questions(engine, mock_db, step, count, picker=None):
    """Answer `count` sequential questions and return (list_of_answered_qids, last_step).

    If fewer questions are available, returns however many were answered.
    Auto-evaluated questions are automatically skipped by the engine, so
    the returned qids are only user-facing ones.
    """
    if picker is None:
        picker = _pick_answer
    answered_qids = []
    for _ in range(count):
        if not isinstance(step, QuestionsStep):
            break
        if step.phase not in (4, 5):
            break
        q = step.questions[0]
        answered_qids.append(q.qid)
        answer = picker(q)
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=answer,
        )
    return answered_qids, step


# =====================================================================
# Test: Error cases
# =====================================================================


class TestStepBackErrors:
    """Verify that step_back raises appropriate errors for invalid states."""

    @pytest.mark.asyncio
    async def test_step_back_from_phase0_raises_value_error(
        self, engine, mock_db,
    ):
        """Cannot go back from phase 0 — it's the very first step."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        with pytest.raises(ValueError, match="already at the first step"):
            await engine.step_back(mock_db, user_id="u1", session_id="s1")

    @pytest.mark.asyncio
    async def test_step_back_on_terminated_session_raises(
        self, engine, mock_db, mock_repo,
    ):
        """Cannot step back on a session terminated by ER positive."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.TERMINATED
        row.terminated_at_phase = 1

        with pytest.raises(ValueError, match="status"):
            await engine.step_back(mock_db, user_id="u1", session_id="s1")

    @pytest.mark.asyncio
    async def test_step_back_on_completed_session_raises(
        self, engine, mock_db, mock_repo,
    ):
        """Cannot step back on a completed session."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.COMPLETED
        row.result = {"departments": ["dept001"], "severity": "sev001"}

        with pytest.raises(ValueError, match="status"):
            await engine.step_back(mock_db, user_id="u1", session_id="s1")


# =====================================================================
# Test: Bulk phase transitions (phases 1 → 0, 2 → 1, 3 → 2)
# =====================================================================


class TestStepBackBulkPhases:
    """Verify step_back navigates correctly between bulk phases (0-3)."""

    @pytest.mark.asyncio
    async def test_phase1_back_to_phase0(self, engine, mock_db):
        """Phase 1 (ER Critical) → step_back → Phase 0 (Demographics)."""
        await _advance_to_phase(engine, mock_db, target_phase=1)
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 0, "Should go back to phase 0"
        assert step.phase_name == "Demographics"

    @pytest.mark.asyncio
    async def test_phase1_back_to_phase0_has_previous_values(
        self, engine, mock_db,
    ):
        """After going back to phase 0, questions carry previous_value metadata."""
        await _advance_to_phase(engine, mock_db, target_phase=1)
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        # At least one question should have previous_value from demographics
        has_previous = any(
            q.metadata and q.metadata.get("previous_value") is not None
            for q in step.questions
        )
        assert has_previous, (
            "Demographics questions should include previous_value metadata "
            "after step_back"
        )

    @pytest.mark.asyncio
    async def test_phase2_back_to_phase1(self, engine, mock_db):
        """Phase 2 (Symptom Selection) → step_back → Phase 1 (ER Critical)."""
        await _advance_to_phase(engine, mock_db, target_phase=2)
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should go back to phase 1"
        assert step.phase_name == "ER Critical Screen"

    @pytest.mark.asyncio
    async def test_phase2_back_to_phase1_has_previous_values(
        self, engine, mock_db,
    ):
        """After going back to phase 1, ER questions carry previous_value metadata."""
        await _advance_to_phase(engine, mock_db, target_phase=2)
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        # ER critical questions should carry previous_value (all False)
        has_previous = any(
            q.metadata and q.metadata.get("previous_value") is not None
            for q in step.questions
        )
        assert has_previous, (
            "ER critical questions should include previous_value metadata "
            "after step_back"
        )

    @pytest.mark.asyncio
    async def test_phase3_back_to_phase2(self, engine, mock_db):
        """Phase 3 (ER Checklist) → step_back → Phase 2 (Symptom Selection)."""
        await _advance_to_phase(engine, mock_db, target_phase=3)
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 2, "Should go back to phase 2"
        assert step.phase_name == "Symptom Selection"

    @pytest.mark.asyncio
    async def test_phase3_back_to_phase2_has_previous_values(
        self, engine, mock_db,
    ):
        """After going back to phase 2, symptom questions carry previous_value."""
        await _advance_to_phase(engine, mock_db, target_phase=3)
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        has_previous = any(
            q.metadata and q.metadata.get("previous_value") is not None
            for q in step.questions
        )
        assert has_previous, (
            "Symptom selection should include previous_value after step_back"
        )


# =====================================================================
# Test: Phase 4 (OLDCARTS) step_back scenarios
# =====================================================================


class TestStepBackPhase4:
    """Verify step_back from phase 4 (OLDCARTS) — both with and without answers."""

    @pytest.mark.asyncio
    async def test_phase4_no_answers_back_to_phase3(
        self, engine, mock_db, mock_repo,
    ):
        """Phase 4 with no user-answered OLDCARTS questions → back to phase 3."""
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved entirely")

        # Check if any OLDCARTS qids have been answered already
        # (auto-evaluated conditionals may have been recorded during transition)
        row = mock_repo._sessions[("u1", "s1")]
        store = engine._store
        oldcarts_qids = set(store.oldcarts.get("Headache", {}).keys())
        has_user_answers = any(
            qid in row.responses
            and isinstance(row.responses[qid], dict)
            and "answered_at" in row.responses[qid]
            for qid in oldcarts_qids
        )

        if has_user_answers:
            pytest.skip(
                "Setup auto-answered OLDCARTS questions during phase transition"
            )

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 3, "Should go back to phase 3 (ER Checklist)"

    @pytest.mark.asyncio
    async def test_phase4_with_answers_back_to_last_answered(
        self, engine, mock_db, mock_repo,
    ):
        """Phase 4 after answering some questions → back to the last answered qid."""
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved entirely")

        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=3,
        )
        if len(answered_qids) < 2:
            pytest.skip("Not enough sequential questions to test step_back")

        last_answered = answered_qids[-1]

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        # The step-back should return a question in phase 4
        assert step.phase == 4, f"Expected phase 4, got {step.phase}"

        # The last answered qid should be removed from responses
        row = mock_repo._sessions[("u1", "s1")]
        assert last_answered not in row.responses, (
            f"Last answered qid {last_answered} should be removed after step_back"
        )

    @pytest.mark.asyncio
    async def test_phase4_step_back_re_presents_question(
        self, engine, mock_db,
    ):
        """After step_back in phase 4, the question can be re-answered and advances."""
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=2,
        )
        if len(answered_qids) < 2:
            pytest.skip("Not enough sequential questions")

        # Step back
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"

        # Re-answer the question — session should advance normally
        q = step.questions[0]
        answer = _pick_answer(q)
        next_step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=answer,
        )
        # Should not be stuck — either advances or presents the next question
        assert next_step is not None, "Re-submission should produce a next step"

    @pytest.mark.asyncio
    async def test_phase4_never_shows_auto_eval_question(
        self, engine, mock_db,
    ):
        """step_back in phase 4 never presents an auto-evaluated question to the user."""
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=3,
        )
        if len(answered_qids) < 2:
            pytest.skip("Not enough sequential questions")

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        if isinstance(step, QuestionsStep) and step.questions:
            qtype = step.questions[0].question_type
            assert qtype not in AUTO_EVAL_TYPES, (
                f"step_back should not present auto-evaluated question type "
                f"'{qtype}' — these should be skipped automatically"
            )


# =====================================================================
# Test: Phase 5 (OPD) step_back scenarios
# =====================================================================


class TestStepBackPhase5:
    """Verify step_back from phase 5 (OPD) — various answer states.

    Uses the "Wound" symptom because its OPD tree has multiple user-facing
    single_select questions (unlike most symptoms whose OPD trees are
    entirely conditional/auto-evaluated).  The ``_pick_answer_last``
    strategy is used to avoid early-terminate branches.
    """

    # Wound is the symptom with the richest user-facing OPD path.
    _SYMPTOM = "Wound"

    @pytest.mark.asyncio
    async def test_phase5_with_opd_answers_back_to_last_opd(
        self, engine, mock_db, mock_repo,
    ):
        """Phase 5 with OPD answers → back to last answered OPD question.

        Only answers 1 OPD question (out of 2 for Wound), then steps back
        before the session completes.
        """
        step = await _advance_to_phase(
            engine, mock_db, target_phase=5,
            symptom=self._SYMPTOM, picker=_pick_answer_last,
        )
        if not isinstance(step, QuestionsStep) or step.phase != 5:
            pytest.skip("Could not reach phase 5 with user-facing OPD questions")

        # Answer only 1 OPD question so the session stays active
        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=1, picker=_pick_answer_last,
        )
        if len(answered_qids) < 1:
            pytest.skip("Not enough OPD questions to test step_back")

        last_answered = answered_qids[-1]

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 5, f"Expected phase 5, got {step.phase}"

        # Verify the last answered qid was removed
        row = mock_repo._sessions[("u1", "s1")]
        assert last_answered not in row.responses, (
            f"Last OPD qid {last_answered} should be removed after step_back"
        )

    @pytest.mark.asyncio
    async def test_phase5_no_opd_answers_back_to_oldcarts(
        self, engine, mock_db, mock_repo,
    ):
        """Phase 5 with no OPD answers but has OLDCARTS → back to last OLDCARTS qid."""
        step = await _advance_to_phase(
            engine, mock_db, target_phase=5,
            symptom=self._SYMPTOM, picker=_pick_answer_last,
        )
        if not isinstance(step, QuestionsStep) or step.phase != 5:
            pytest.skip("Could not reach phase 5")

        # Don't answer any OPD questions — step_back from here.
        # The engine should find the last OLDCARTS answer instead.
        row = mock_repo._sessions[("u1", "s1")]
        store = engine._store
        oldcarts_qids = set(store.oldcarts.get(self._SYMPTOM, {}).keys())
        has_oldcarts = any(
            qid in row.responses
            and isinstance(row.responses[qid], dict)
            and "answered_at" in row.responses[qid]
            for qid in oldcarts_qids
        )

        if not has_oldcarts:
            pytest.skip("No OLDCARTS answers — cannot test cross-phase step_back")

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 4, (
            f"With no OPD answers, should go back to phase 4 (OLDCARTS), "
            f"got phase {step.phase}"
        )

    @pytest.mark.asyncio
    async def test_phase5_never_shows_auto_eval_question(
        self, engine, mock_db,
    ):
        """step_back in phase 5 never presents an auto-evaluated question."""
        step = await _advance_to_phase(
            engine, mock_db, target_phase=5,
            symptom=self._SYMPTOM, picker=_pick_answer_last,
        )
        if not isinstance(step, QuestionsStep) or step.phase != 5:
            pytest.skip("Could not reach phase 5")

        # Answer only 1 question to keep the session active
        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=1, picker=_pick_answer_last,
        )
        if len(answered_qids) < 1:
            pytest.skip("Not enough OPD questions")

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        if isinstance(step, QuestionsStep) and step.questions:
            qtype = step.questions[0].question_type
            assert qtype not in AUTO_EVAL_TYPES, (
                f"step_back should not present auto-evaluated question type "
                f"'{qtype}' in phase 5"
            )

    @pytest.mark.asyncio
    async def test_phase5_step_back_re_presents_question(
        self, engine, mock_db,
    ):
        """After step_back in phase 5, the question can be re-answered and advances."""
        step = await _advance_to_phase(
            engine, mock_db, target_phase=5,
            symptom=self._SYMPTOM, picker=_pick_answer_last,
        )
        if not isinstance(step, QuestionsStep) or step.phase != 5:
            pytest.skip("Could not reach phase 5")

        # Answer only 1 question to keep the session active
        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=1, picker=_pick_answer_last,
        )
        if len(answered_qids) < 1:
            pytest.skip("Not enough OPD questions")

        # Step back
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"

        # Re-answer the question — session should advance normally
        q = step.questions[0]
        answer = _pick_answer_last(q)
        next_step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=answer,
        )
        assert next_step is not None, "Re-submission should produce a next step"


# =====================================================================
# Test: Consecutive step_back calls (multi-step rewind)
# =====================================================================


class TestStepBackConsecutive:
    """Verify that multiple consecutive step_back calls work correctly."""

    @pytest.mark.asyncio
    async def test_phase3_back_twice_reaches_phase1(self, engine, mock_db):
        """From phase 3, two step_backs should reach phase 1."""
        await _advance_to_phase(engine, mock_db, target_phase=3)

        # First step_back: phase 3 → 2
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 2, "First step_back: should be at phase 2"

        # Second step_back: phase 2 → 1
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Second step_back: should be at phase 1"

    @pytest.mark.asyncio
    async def test_phase3_back_three_times_reaches_phase0(self, engine, mock_db):
        """From phase 3, three step_backs should reach phase 0."""
        await _advance_to_phase(engine, mock_db, target_phase=3)

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert step.phase == 2, "First step_back: phase 2"

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert step.phase == 1, "Second step_back: phase 1"

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert step.phase == 0, "Third step_back: phase 0"

    @pytest.mark.asyncio
    async def test_phase3_back_four_times_raises_at_phase0(self, engine, mock_db):
        """From phase 3, four step_backs should raise at phase 0."""
        await _advance_to_phase(engine, mock_db, target_phase=3)

        await engine.step_back(mock_db, user_id="u1", session_id="s1")
        await engine.step_back(mock_db, user_id="u1", session_id="s1")
        await engine.step_back(mock_db, user_id="u1", session_id="s1")

        # Fourth step_back from phase 0 should raise
        with pytest.raises(ValueError, match="already at the first step"):
            await engine.step_back(mock_db, user_id="u1", session_id="s1")

    @pytest.mark.asyncio
    async def test_consecutive_back_from_phase4_with_answers(
        self, engine, mock_db, mock_repo,
    ):
        """Consecutive step_backs from phase 4 after answering questions.

        First step_back reverts the last OLDCARTS answer; if we keep
        going back we should eventually reach phase 3 and then bulk phases.
        """
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=3,
        )
        if len(answered_qids) < 2:
            pytest.skip("Not enough OLDCARTS questions")

        # First step_back: should stay in phase 4
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"

        # Keep stepping back until we exit phase 4
        max_steps = len(answered_qids) + 5  # safety limit
        for _ in range(max_steps):
            row = mock_repo._sessions[("u1", "s1")]
            if row.current_phase < 4:
                break
            try:
                step = await engine.step_back(
                    mock_db, user_id="u1", session_id="s1",
                )
            except ValueError:
                break

        # We should eventually reach phase 3 or earlier
        row = mock_repo._sessions[("u1", "s1")]
        assert row.current_phase <= 3, (
            f"After enough step_backs, should exit phase 4; "
            f"current_phase is {row.current_phase}"
        )


# =====================================================================
# Test: Round-trip (step_back + re-submit)
# =====================================================================


class TestStepBackRoundTrip:
    """Verify that step_back followed by re-submission advances normally."""

    @pytest.mark.asyncio
    async def test_phase1_back_to_phase0_then_resubmit(self, engine, mock_db):
        """Step back to phase 0, resubmit demographics → advance to phase 1."""
        await _advance_to_phase(engine, mock_db, target_phase=1)

        # Step back to phase 0
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert step.phase == 0

        # Resubmit demographics
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Resubmitting demographics should advance to phase 1"

    @pytest.mark.asyncio
    async def test_phase2_back_to_phase1_then_resubmit(self, engine, mock_db):
        """Step back to phase 1, resubmit ER critical → advance to phase 2."""
        await _advance_to_phase(engine, mock_db, target_phase=2)

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert step.phase == 1

        store = engine._store
        er_responses = {item.qid: False for item in store.er_critical}
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 2, "Resubmitting ER critical should advance to phase 2"

    @pytest.mark.asyncio
    async def test_phase3_back_to_phase2_then_resubmit(self, engine, mock_db):
        """Step back to phase 2, resubmit symptoms → advance to phase 3."""
        await _advance_to_phase(engine, mock_db, target_phase=3)

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert step.phase == 2

        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms",
            value={"primary_symptom": "Headache"},
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 3, "Resubmitting symptoms should advance to phase 3"

    @pytest.mark.asyncio
    async def test_phase4_back_to_phase3_then_resubmit(
        self, engine, mock_db, mock_repo,
    ):
        """Step back from phase 4 (no answers) to phase 3, resubmit → phase 4."""
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        # Check if we can step back to phase 3
        row = mock_repo._sessions[("u1", "s1")]
        store = engine._store
        oldcarts_qids = set(store.oldcarts.get("Headache", {}).keys())
        has_answers = any(
            qid in row.responses
            and isinstance(row.responses[qid], dict)
            and "answered_at" in row.responses[qid]
            for qid in oldcarts_qids
        )
        if has_answers:
            pytest.skip("Setup auto-answered OLDCARTS questions")

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert step.phase == 3, "Should go back to phase 3"

        # Resubmit ER checklist
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 4, "Resubmitting ER checklist should advance to phase 4"


# =====================================================================
# Test: Conditional/auto-eval questions are skipped during step_back
# =====================================================================


class TestStepBackConditionalSkipping:
    """Verify that auto-evaluated questions (conditional, gender_filter,
    age_filter) are never returned to the user during step_back.

    The engine auto-resolves these transparently. When stepping back, the
    engine should present the last *user-facing* question, not a conditional
    that happens to be in the tree.
    """

    @pytest.mark.asyncio
    async def test_step_back_skips_conditionals_in_phase4(
        self, engine, mock_db, mock_repo,
    ):
        """Answering through OLDCARTS (which may contain conditionals), then
        stepping back, should always present a user-facing question type.
        """
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        # Answer enough questions to potentially hit conditional branches
        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=5,
        )
        if len(answered_qids) < 2:
            pytest.skip("Not enough sequential questions")

        # Step back — should never show a conditional/filter question
        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        for q in step.questions:
            assert q.question_type not in AUTO_EVAL_TYPES, (
                f"step_back presented auto-evaluated question type "
                f"'{q.question_type}' (qid: {q.qid}) — should be skipped"
            )

    @pytest.mark.asyncio
    async def test_step_back_skips_conditionals_in_phase5(
        self, engine, mock_db,
    ):
        """OPD trees use conditionals heavily. step_back should skip them.

        Uses Wound symptom since it has user-facing OPD questions.
        Answers only 1 question to keep the session active.
        """
        step = await _advance_to_phase(
            engine, mock_db, target_phase=5,
            symptom="Wound", picker=_pick_answer_last,
        )
        if not isinstance(step, QuestionsStep) or step.phase != 5:
            pytest.skip("Could not reach phase 5")

        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=1, picker=_pick_answer_last,
        )
        if len(answered_qids) < 1:
            pytest.skip("Not enough OPD questions")

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        if isinstance(step, QuestionsStep) and step.questions:
            for q in step.questions:
                assert q.question_type not in AUTO_EVAL_TYPES, (
                    f"step_back presented auto-evaluated question type "
                    f"'{q.question_type}' (qid: {q.qid}) in phase 5"
                )

    @pytest.mark.asyncio
    async def test_multiple_step_backs_never_show_auto_eval(
        self, engine, mock_db, mock_repo,
    ):
        """Multiple consecutive step_backs never show auto-evaluated questions."""
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        answered_qids, step = await _answer_sequential_questions(
            engine, mock_db, step, count=5,
        )
        if len(answered_qids) < 3:
            pytest.skip("Not enough sequential questions")

        # Step back multiple times, checking each result
        for i in range(min(len(answered_qids), 4)):
            row = mock_repo._sessions[("u1", "s1")]
            if row.current_phase == 0:
                break
            try:
                step = await engine.step_back(
                    mock_db, user_id="u1", session_id="s1",
                )
            except ValueError:
                break  # hit phase 0

            if isinstance(step, QuestionsStep) and step.questions:
                for q in step.questions:
                    assert q.question_type not in AUTO_EVAL_TYPES, (
                        f"step_back #{i+1} presented auto-evaluated type "
                        f"'{q.question_type}' (qid: {q.qid})"
                    )


# =====================================================================
# Test: State integrity after step_back
# =====================================================================


class TestStepBackStateIntegrity:
    """Verify that session state is correctly modified after step_back."""

    @pytest.mark.asyncio
    async def test_demographics_cleared_when_back_to_phase0(
        self, engine, mock_db, mock_repo,
    ):
        """Going back to phase 0 clears demographics from session state."""
        await _advance_to_phase(engine, mock_db, target_phase=1)
        await engine.step_back(mock_db, user_id="u1", session_id="s1")

        row = mock_repo._sessions[("u1", "s1")]
        assert row.current_phase == 0, "Should be at phase 0"
        assert row.demographics == {}, "Demographics should be cleared"

    @pytest.mark.asyncio
    async def test_symptoms_cleared_when_back_to_phase1(
        self, engine, mock_db, mock_repo,
    ):
        """Going back to phase 1 clears symptoms from session state."""
        await _advance_to_phase(engine, mock_db, target_phase=3)
        # Step back to phase 2, then phase 1
        await engine.step_back(mock_db, user_id="u1", session_id="s1")
        await engine.step_back(mock_db, user_id="u1", session_id="s1")

        row = mock_repo._sessions[("u1", "s1")]
        assert row.current_phase == 1, "Should be at phase 1"
        assert row.primary_symptom is None, "Primary symptom should be cleared"
        assert row.secondary_symptoms is None, "Secondary symptoms should be cleared"

    @pytest.mark.asyncio
    async def test_symptoms_cleared_when_back_to_phase2(
        self, engine, mock_db, mock_repo,
    ):
        """Going back to phase 2 clears symptoms (they need to be re-entered)."""
        await _advance_to_phase(engine, mock_db, target_phase=3)
        await engine.step_back(mock_db, user_id="u1", session_id="s1")

        row = mock_repo._sessions[("u1", "s1")]
        assert row.current_phase == 2, "Should be at phase 2"
        assert row.primary_symptom is None, "Primary symptom should be cleared"

    @pytest.mark.asyncio
    async def test_er_flags_cleared_when_back_to_phase3(
        self, engine, mock_db, mock_repo,
    ):
        """Going back to phase 3 clears ER flags."""
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        # Check if we can go back to phase 3
        row = mock_repo._sessions[("u1", "s1")]
        store = engine._store
        oldcarts_qids = set(store.oldcarts.get("Headache", {}).keys())
        has_answers = any(
            qid in row.responses
            and isinstance(row.responses[qid], dict)
            and "answered_at" in row.responses[qid]
            for qid in oldcarts_qids
        )

        if has_answers:
            pytest.skip("Has OLDCARTS answers — step_back won't reach phase 3")

        await engine.step_back(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        assert row.current_phase == 3, "Should be at phase 3"
        assert row.er_flags is None, "ER flags should be cleared"

    @pytest.mark.asyncio
    async def test_phase4_responses_removed_after_step_back(
        self, engine, mock_db, mock_repo,
    ):
        """step_back in phase 4 removes the last answered response."""
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        answered_qids, _ = await _answer_sequential_questions(
            engine, mock_db, step, count=3,
        )
        if len(answered_qids) < 2:
            pytest.skip("Not enough sequential questions")

        # Record the responses before step_back
        row = mock_repo._sessions[("u1", "s1")]
        responses_before = dict(row.responses)

        await engine.step_back(mock_db, user_id="u1", session_id="s1")

        # The last answered qid should be absent from responses
        last = answered_qids[-1]
        assert last not in row.responses, (
            f"qid {last} should be removed from responses after step_back"
        )
        # Earlier answered qids should still be present
        for qid in answered_qids[:-1]:
            if qid in responses_before:
                assert qid in row.responses, (
                    f"Earlier qid {qid} should still be in responses"
                )

    @pytest.mark.asyncio
    async def test_session_status_preserved_after_step_back(
        self, engine, mock_db, mock_repo,
    ):
        """step_back preserves session status as IN_PROGRESS (doesn't reset to CREATED)."""
        await _advance_to_phase(engine, mock_db, target_phase=3)

        row = mock_repo._sessions[("u1", "s1")]
        assert row.status == SessionStatus.IN_PROGRESS, "Should be in_progress"

        await engine.step_back(mock_db, user_id="u1", session_id="s1")

        # Status should remain in_progress (or created if back at phase 0)
        assert row.status in (SessionStatus.CREATED, SessionStatus.IN_PROGRESS), (
            f"Status should be created or in_progress, got {row.status}"
        )


# =====================================================================
# Test: Full rewind from deep phase back to phase 0
# =====================================================================


class TestStepBackFullRewind:
    """Verify rewinding from a deep phase all the way back to phase 0."""

    @pytest.mark.asyncio
    async def test_full_rewind_from_phase4_to_phase0(
        self, engine, mock_db, mock_repo,
    ):
        """From phase 4, keep stepping back until phase 0. All phases should
        appear in reverse order and no auto-eval questions should be shown.
        """
        step = await _advance_to_phase(engine, mock_db, target_phase=4)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        # Answer a couple OLDCARTS questions
        answered_qids, _ = await _answer_sequential_questions(
            engine, mock_db, step, count=2,
        )

        # Now rewind all the way
        visited_phases = []
        max_attempts = 20  # safety limit

        for _ in range(max_attempts):
            try:
                step = await engine.step_back(
                    mock_db, user_id="u1", session_id="s1",
                )
                if isinstance(step, QuestionsStep):
                    visited_phases.append(step.phase)

                    # Verify no auto-eval questions
                    for q in step.questions:
                        assert q.question_type not in AUTO_EVAL_TYPES, (
                            f"Auto-eval type '{q.question_type}' shown at "
                            f"phase {step.phase}"
                        )
            except ValueError:
                break

        # Should have visited phase 0 at some point
        assert 0 in visited_phases, (
            f"Full rewind should reach phase 0; visited: {visited_phases}"
        )

        # Verify final state is phase 0
        row = mock_repo._sessions[("u1", "s1")]
        assert row.current_phase == 0, (
            f"After full rewind, should be at phase 0, got {row.current_phase}"
        )


# =====================================================================
# Test: Different symptom selections
# =====================================================================


class TestStepBackDifferentSymptoms:
    """Verify step_back works with different symptom selections.

    Different symptoms produce different OLDCARTS/OPD decision trees,
    so we test with a few representative symptoms.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("symptom", ["Stomachache", "Fever", "Cough"])
    async def test_step_back_from_phase4_with_different_symptoms(
        self, engine, mock_db, mock_repo, symptom,
    ):
        """step_back from phase 4 works for different symptom types."""
        step = await _advance_to_phase(
            engine, mock_db, target_phase=4, symptom=symptom,
        )
        if not isinstance(step, QuestionsStep):
            pytest.skip(f"OLDCARTS tree for {symptom} auto-resolved")

        answered_qids, _ = await _answer_sequential_questions(
            engine, mock_db, step, count=2,
        )
        if len(answered_qids) < 1:
            pytest.skip(f"Not enough OLDCARTS questions for {symptom}")

        step = await engine.step_back(mock_db, user_id="u1", session_id="s1")
        assert isinstance(step, QuestionsStep), (
            f"Expected QuestionsStep after step_back for {symptom}"
        )
        # Must not show auto-eval question types
        for q in step.questions:
            assert q.question_type not in AUTO_EVAL_TYPES, (
                f"Auto-eval type '{q.question_type}' shown for symptom "
                f"'{symptom}' (qid: {q.qid})"
            )
