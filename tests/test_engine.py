"""PrescreenEngine tests with mocked DB layer.

Uses MockSessionRow (a plain dataclass mimicking PrescreenSession) and
MockRepository (in-memory dict implementing the SessionRepository interface)
to test engine orchestration without a real database.

Mock strategy:
  - MockSessionRow has the same attributes as PrescreenSession but no
    SQLAlchemy dependency.  The engine reads/writes attributes directly.
  - MockRepository implements every async method the engine calls,
    mutating MockSessionRow in-place just like the real repository.
  - AsyncMock stands in for AsyncSession (db); flush() is a no-op.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from prescreen_db.models.enums import SessionStatus
from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.models.session import QuestionsStep, TerminationStep
from prescreen_rulesets.ruleset import RulesetStore


# =====================================================================
# Mock infrastructure
# =====================================================================


@dataclass
class MockSessionRow:
    """In-memory stand-in for PrescreenSession ORM model.

    Provides the same attributes as the real ORM model but without
    SQLAlchemy overhead.  The engine accesses these attributes directly
    (e.g. row.current_phase, row.responses).
    """

    user_id: str = "user1"
    session_id: str = "sess1"
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: SessionStatus = SessionStatus.CREATED
    current_phase: int = 0
    ruleset_version: str | None = None
    demographics: dict = field(default_factory=dict)
    primary_symptom: str | None = None
    secondary_symptoms: list[str] | None = None
    responses: dict = field(default_factory=dict)
    er_flags: dict | None = None
    result: dict | None = None
    terminated_at_phase: int | None = None
    termination_reason: str | None = None
    # Pipeline-stage fields (used by PrescreenPipeline)
    pipeline_stage: str = "rule_based"
    llm_questions: list | None = None
    llm_responses: list | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None


class MockRepository:
    """In-memory SessionRepository replacement.

    Stores MockSessionRow instances in a dict keyed by (user_id, session_id).
    Each method mirrors the real SessionRepository's interface and side
    effects so the engine behaves identically.
    """

    def __init__(self):
        self._sessions: dict[tuple[str, str], MockSessionRow] = {}

    async def create_session(
        self, db, *, user_id, session_id, ruleset_version=None,
    ):
        row = MockSessionRow(
            user_id=user_id,
            session_id=session_id,
            ruleset_version=ruleset_version,
        )
        self._sessions[(user_id, session_id)] = row
        return row

    async def get_by_user_and_session(self, db, user_id, session_id):
        return self._sessions.get((user_id, session_id))

    async def save_demographics(self, db, session, demographics):
        merged = {**session.demographics, **demographics}
        session.demographics = merged
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def record_response(self, db, session, qid, value):
        entry = {
            "value": value,
            "answered_at": datetime.now(timezone.utc).isoformat(),
        }
        updated = {**session.responses, qid: entry}
        session.responses = updated
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def save_symptom_selection(
        self, db, session, *, primary_symptom, secondary_symptoms=None,
    ):
        session.primary_symptom = primary_symptom
        session.secondary_symptoms = secondary_symptoms
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def advance_phase(self, db, session, next_phase):
        session.current_phase = next_phase
        if session.status == SessionStatus.CREATED:
            session.status = SessionStatus.IN_PROGRESS
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def save_er_flags(self, db, session, er_flags):
        session.er_flags = er_flags
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def terminate_session(self, db, session, *, phase, reason):
        now = datetime.now(timezone.utc)
        session.status = SessionStatus.TERMINATED
        session.terminated_at_phase = phase
        session.termination_reason = reason
        session.completed_at = now
        session.updated_at = now
        return session

    async def complete_session(self, db, session, result):
        now = datetime.now(timezone.utc)
        session.status = SessionStatus.COMPLETED
        session.result = result
        session.completed_at = now
        session.updated_at = now
        return session

    # Pipeline-stage methods (used by PrescreenPipeline)

    async def set_pipeline_stage(self, db, session, stage):
        session.pipeline_stage = stage.value
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def save_llm_questions(self, db, session, questions):
        session.llm_questions = questions
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def save_llm_responses(self, db, session, responses):
        session.llm_responses = responses
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def list_by_user(self, db, user_id, *, limit=20, offset=0):
        return [
            row for (uid, _), row in self._sessions.items()
            if uid == user_id
        ][:limit]


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
# Phase 0: Demographics
# =====================================================================


class TestPhase0Demographics:
    """Tests for session creation and demographics submission."""

    @pytest.mark.asyncio
    async def test_create_session_returns_session_info(self, engine, mock_db):
        """create_session returns a SessionInfo with correct fields."""
        info = await engine.create_session(
            mock_db, user_id="u1", session_id="s1",
        )
        assert info.user_id == "u1", "user_id mismatch"
        assert info.session_id == "s1", "session_id mismatch"
        assert info.status == "created", "New session should be 'created'"
        assert info.current_phase == 0, "New session should start at phase 0"

    @pytest.mark.asyncio
    async def test_get_current_step_phase0_returns_demographics(
        self, engine, mock_db,
    ):
        """At phase 0, get_current_step returns demographics questions."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        step = await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 0, "Phase should be 0"
        assert step.phase_name == "Demographics", "Phase name mismatch"
        assert len(step.questions) == 8, (
            f"Expected 8 demographic questions, got {len(step.questions)}"
        )

    @pytest.mark.asyncio
    async def test_submit_demographics_advances_to_phase1(
        self, engine, mock_db,
    ):
        """Submitting demographics advances the session to phase 1."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        demographics = {
            "date_of_birth": "1994-06-15",
            "gender": "Male",
            "height": 175,
            "weight": 70,
        }
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=demographics,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should advance to phase 1"
        assert step.phase_name == "ER Critical Screen"


# =====================================================================
# Phase 1: ER Critical Screen
# =====================================================================


class TestPhase1ERCritical:
    """Tests for ER critical screen submission."""

    async def _setup_phase1(self, engine, mock_db):
        """Create a session and advance to phase 1."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value={"gender": "Male", "age": 30},
        )

    @pytest.mark.asyncio
    async def test_er_critical_all_negative_advances(self, engine, mock_db):
        """All-negative ER critical responses advance to phase 2."""
        await self._setup_phase1(engine, mock_db)
        store = engine._store
        er_responses = {item.qid: False for item in store.er_critical}

        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 2, "Should advance to phase 2"

    @pytest.mark.asyncio
    async def test_er_critical_one_positive_terminates(self, engine, mock_db):
        """One positive ER critical response terminates the session."""
        await self._setup_phase1(engine, mock_db)
        store = engine._store
        er_responses = {item.qid: False for item in store.er_critical}

        # Set the first critical item to positive
        first_qid = store.er_critical[0].qid
        er_responses[first_qid] = True

        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        assert isinstance(step, TerminationStep), "Expected TerminationStep"
        assert step.type == "terminated", "Should be 'terminated'"
        # ER critical always routes to dept002 (Emergency) with sev003
        assert any(d["id"] == "dept002" for d in step.departments), (
            "Should route to Emergency Medicine (dept002)"
        )
        assert step.severity["id"] == "sev003", "Should be Emergency severity"


# =====================================================================
# Phase 2: Symptom Selection
# =====================================================================


class TestPhase2Symptoms:
    """Tests for symptom selection submission."""

    async def _setup_phase2(self, engine, mock_db):
        """Create session and advance to phase 2."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value={"gender": "Male", "age": 30},
        )
        store = engine._store
        er_responses = {item.qid: False for item in store.er_critical}
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )

    @pytest.mark.asyncio
    async def test_symptom_selection_advances(self, engine, mock_db):
        """Submitting symptom selection advances to phase 3."""
        await self._setup_phase2(engine, mock_db)
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms",
            value={"primary_symptom": "Headache", "secondary_symptoms": []},
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 3, "Should advance to phase 3"


# =====================================================================
# Phase 3: ER Checklist
# =====================================================================


class TestPhase3ERChecklist:
    """Tests for ER checklist submission."""

    async def _setup_phase3(self, engine, mock_db):
        """Create session and advance to phase 3 with 'Headache' selected."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value={"gender": "Male", "age": 30},
        )
        store = engine._store
        er_responses = {item.qid: False for item in store.er_critical}
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms",
            value={"primary_symptom": "Headache"},
        )

    @pytest.mark.asyncio
    async def test_er_checklist_all_negative_advances(self, engine, mock_db):
        """All-negative ER checklist advances to phase 4 (OLDCARTS)."""
        await self._setup_phase3(engine, mock_db)
        store = engine._store
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}

        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )
        # Should advance to sequential phase (4 or 5, depending on
        # whether OLDCARTS auto-eval questions resolve immediately)
        assert isinstance(step, (QuestionsStep, TerminationStep)), (
            "Expected QuestionsStep or TerminationStep"
        )
        if isinstance(step, QuestionsStep):
            assert step.phase >= 4, f"Expected phase >= 4, got {step.phase}"

    @pytest.mark.asyncio
    async def test_er_checklist_positive_terminates(self, engine, mock_db):
        """One positive ER checklist item terminates the session."""
        await self._setup_phase3(engine, mock_db)
        store = engine._store
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        assert checklist_items, "Expected non-empty checklist for Headache"

        checklist_responses = {item.qid: False for item in checklist_items}
        # Set first item to positive
        checklist_responses[checklist_items[0].qid] = True

        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )
        assert isinstance(step, TerminationStep), "Expected TerminationStep"
        assert step.type == "terminated", "Should be 'terminated'"


# =====================================================================
# Phases 4/5: Sequential (OLDCARTS / OPD)
# =====================================================================


class TestPhase4Sequential:
    """Tests for sequential OLDCARTS question handling."""

    async def _setup_phase4(self, engine, mock_db):
        """Create session and advance to phase 4 (OLDCARTS)."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value={"gender": "Male", "age": 30},
        )
        store = engine._store
        er_responses = {item.qid: False for item in store.er_critical}
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms",
            value={"primary_symptom": "Headache"},
        )
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )

    @pytest.mark.asyncio
    async def test_sequential_returns_first_question(self, engine, mock_db):
        """Phase 4 get_current_step returns a question for the symptom tree."""
        await self._setup_phase4(engine, mock_db)
        step = await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        # May be a question step or termination (if the tree auto-resolves)
        assert isinstance(step, (QuestionsStep, TerminationStep)), (
            "Expected QuestionsStep or TerminationStep"
        )
        if isinstance(step, QuestionsStep):
            assert step.phase in (4, 5), (
                f"Expected phase 4 or 5, got {step.phase}"
            )
            assert len(step.questions) > 0, "Should have at least one question"


# =====================================================================
# Edge cases
# =====================================================================


class TestEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, engine, mock_db):
        """get_session returns None for a non-existent session."""
        result = await engine.get_session(
            mock_db, user_id="nonexistent", session_id="nope",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_already_terminated_returns_termination_step(
        self, engine, mock_db, mock_repo,
    ):
        """get_current_step on a terminated session returns TerminationStep."""
        # Create a session and manually put it in terminated state
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.TERMINATED
        row.terminated_at_phase = 1
        row.termination_reason = "test termination"
        row.result = {
            "departments": ["dept002"],
            "severity": "sev003",
            "reason": "test",
        }

        step = await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, TerminationStep), "Expected TerminationStep"
        assert step.type == "terminated", "Should be 'terminated'"
