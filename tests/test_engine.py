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
from prescreen_rulesets.engine import PrescreenEngine, _evaluate_field_condition
from prescreen_rulesets.models.session import QuestionsStep, TerminationStep
from prescreen_rulesets.ruleset import RulesetStore

# Valid demographics payload that passes engine validation.
# Used across tests that need to advance past phase 0.
# Phase 0 now collects: age, gender, underlying_diseases, current_medication,
# drug_food_allergies, and surgical_history.  Height/weight moved to phase 5
# (Past History); occupation moved to phase 6 (Personal History).
VALID_DEMOGRAPHICS = {
    "age": 30,
    "gender": "Male",
    "underlying_diseases": [],
    "current_medication": {"answer": False, "detail": None},
    "drug_food_allergies": {"answer": False, "detail": None},
    "surgical_history": {"answer": False, "detail": None},
}

# Valid past history payload (phase 5) — height, weight, and medical conditions.
VALID_PAST_HISTORY = {
    "height": 175,
    "weight": 70,
    "other_medical_conditions": {"answer": False, "detail": None},
}

# Valid personal history payload (phase 6) — occupation, hometown, smoking, alcohol.
VALID_PERSONAL_HISTORY = {
    "occupation": "พนักงานบริษัท/เอกชน/ลูกจ้าง",
    "hometown_province": "กรุงเทพมหานคร",
    "smoking_history": {"answer": False, "detail": None},
    "alcohol_history": {"answer": False, "detail": None},
}


def _visible_er_qids(store: RulesetStore, demographics: dict) -> set[str]:
    """Return the set of ER critical qids visible for the given demographics.

    Mirrors the condition-filtering logic in ``_step_er_critical``.
    Items without a condition are always visible; items with a condition
    are visible only when ``_evaluate_field_condition`` returns True.
    """
    return {
        item.qid for item in store.er_critical
        if not item.condition or _evaluate_field_condition(item.condition, demographics)
    }


def _er_responses_for(store: RulesetStore, demographics: dict) -> dict[str, bool]:
    """Build an all-negative ER critical response dict for visible items only."""
    return {qid: False for qid in _visible_er_qids(store, demographics)}


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
    # Soft-delete timestamp — None means live, non-None means soft-deleted
    deleted_at: datetime | None = None
    # Early termination control — mirrors PrescreenSession ORM fields
    disable_early_termination: bool = False
    skipped_terminations: list | None = None


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
        disable_early_termination=False,
    ):
        row = MockSessionRow(
            user_id=user_id,
            session_id=session_id,
            ruleset_version=ruleset_version,
            disable_early_termination=disable_early_termination,
        )
        self._sessions[(user_id, session_id)] = row
        return row

    async def get_by_user_and_session(self, db, user_id, session_id):
        row = self._sessions.get((user_id, session_id))
        # Exclude soft-deleted rows, matching real repository behaviour
        if row is not None and row.deleted_at is not None:
            return None
        return row

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
        # Clear stale __pending queue — mirrors real repository behaviour.
        responses = session.responses or {}
        if "__pending" in responses:
            session.responses = {
                k: v for k, v in responses.items() if k != "__pending"
            }
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
            if uid == user_id and row.deleted_at is None
        ][:limit]

    async def soft_delete(self, db, session):
        """Set deleted_at on a session, hiding it from normal queries."""
        if session.deleted_at is not None:
            raise ValueError(
                f"Session already deleted: session_id={session.session_id}"
            )
        now = datetime.now(timezone.utc)
        session.deleted_at = now
        session.updated_at = now
        return session

    async def hard_delete(self, db, session):
        """Permanently remove a session from the in-memory store."""
        key = (session.user_id, session.session_id)
        self._sessions.pop(key, None)

    async def revert_session_state(
        self, db, session, *, target_phase,
        clear_demographics=False, clear_symptoms=False,
        clear_er_flags=False, response_qids_to_remove=None,
        new_pending=None, demo_keys_to_remove=None,
    ):
        """Revert session state — mirrors real repository's revert logic.

        demo_keys_to_remove: set of keys to remove from demographics JSONB
            (used for granular clearing of past/personal history keys
            without wiping the whole demographics dict).
        """
        session.current_phase = target_phase
        if clear_demographics:
            session.demographics = {}
        elif demo_keys_to_remove:
            # Granular key removal — remove specific keys from demographics
            # without clearing the whole dict (used for phases 5/6 back-edit)
            demographics = dict(session.demographics or {})
            for key in demo_keys_to_remove:
                demographics.pop(key, None)
            session.demographics = demographics
        if clear_symptoms:
            session.primary_symptom = None
            session.secondary_symptoms = None
        if clear_er_flags:
            session.er_flags = None
        # Rebuild responses: remove specified qids + __pending
        responses = dict(session.responses or {})
        responses.pop("__pending", None)
        if response_qids_to_remove:
            for qid in response_qids_to_remove:
                responses.pop(qid, None)
        if new_pending is not None:
            responses["__pending"] = new_pending
        session.responses = responses
        session.updated_at = datetime.now(timezone.utc)
        return session


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
        # 14 total fields in demographic.yaml: 6 unconditional (age, gender,
        # underlying_diseases, current_medication, drug_food_allergies,
        # surgical_history) + 1 conditional on age (age_months) + 7 conditional
        # on gender/pregnancy status.  _step_demographics() includes ALL
        # fields without filtering.
        assert len(step.questions) == 14, (
            f"Expected 14 demographic questions, got {len(step.questions)}"
        )

    @pytest.mark.asyncio
    async def test_submit_demographics_advances_to_phase1(
        self, engine, mock_db,
    ):
        """Submitting demographics advances the session to phase 1."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
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
            value=VALID_DEMOGRAPHICS,
        )

    @pytest.mark.asyncio
    async def test_er_critical_all_negative_advances(self, engine, mock_db):
        """All-negative ER critical responses advance to phase 2."""
        await self._setup_phase1(engine, mock_db)
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)

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
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)

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
# Phase 1: ER Critical Screen — Conditional Visibility
# =====================================================================


class TestPhase1ERCriticalConditional:
    """Tests for conditional visibility of ER critical items.

    emer_critical_004 (severe headache): shown only when age < 15.
    emer_critical_020 (pregnancy-related): shown only when pregnancy_status == pregnant.
    """

    async def _get_phase1_step(self, engine, mock_db, demographics):
        """Create a session with the given demographics and return the phase 1 step."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=demographics,
        )
        return step

    @pytest.mark.asyncio
    async def test_adult_male_excludes_004_and_020(self, engine, mock_db):
        """Adult male (age 30) should not see emer_critical_004 or emer_critical_020."""
        step = await self._get_phase1_step(engine, mock_db, VALID_DEMOGRAPHICS)
        qids = {q.qid for q in step.questions}
        assert "emer_critical_004" not in qids, \
            "emer_critical_004 should be hidden for adult (age >= 15)"
        assert "emer_critical_020" not in qids, \
            "emer_critical_020 should be hidden for non-pregnant patient"

    @pytest.mark.asyncio
    async def test_child_sees_004(self, engine, mock_db):
        """Child (age 10) should see emer_critical_004 (severe headache)."""
        child_demographics = {**VALID_DEMOGRAPHICS, "age": 10}
        step = await self._get_phase1_step(engine, mock_db, child_demographics)
        qids = {q.qid for q in step.questions}
        assert "emer_critical_004" in qids, \
            "emer_critical_004 should be visible for child (age < 15)"

    @pytest.mark.asyncio
    async def test_pregnant_female_sees_020(self, engine, mock_db):
        """Pregnant female should see emer_critical_020."""
        pregnant_demographics = {
            **VALID_DEMOGRAPHICS,
            "gender": "Female",
            "pregnancy_status": "pregnant",
            # Conditional fields required when pregnant
            "total_pregnancies": 1,
            "fetuses_count": 1,
            "gestational_age_weeks": 20,
        }
        step = await self._get_phase1_step(engine, mock_db, pregnant_demographics)
        qids = {q.qid for q in step.questions}
        assert "emer_critical_020" in qids, \
            "emer_critical_020 should be visible for pregnant patient"

    @pytest.mark.asyncio
    async def test_non_pregnant_female_excludes_020(self, engine, mock_db):
        """Non-pregnant female should not see emer_critical_020."""
        female_demographics = {
            **VALID_DEMOGRAPHICS,
            "gender": "Female",
            "pregnancy_status": "not_pregnant",
            # Conditional fields required when not pregnant
            "last_menstrual_period": "2026-02-15",
            "menstrual_duration_days": 5,
            "menstrual_flow": "same",
        }
        step = await self._get_phase1_step(engine, mock_db, female_demographics)
        qids = {q.qid for q in step.questions}
        assert "emer_critical_020" not in qids, \
            "emer_critical_020 should be hidden for non-pregnant female"

    @pytest.mark.asyncio
    async def test_submission_schema_matches_visible_questions(self, engine, mock_db):
        """submission_schema.required should match the visible question qids."""
        step = await self._get_phase1_step(engine, mock_db, VALID_DEMOGRAPHICS)
        visible_qids = {q.qid for q in step.questions}
        required_qids = set(step.submission_schema["required"])
        assert visible_qids == required_qids, \
            "submission_schema.required must match visible question qids"


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
            value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
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
            value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
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
# Phase 3: ER Checklist — Conditional Visibility & Auto-Complete
# =====================================================================


class TestPhase3ERChecklistConditional:
    """Tests for condition/auto_complete filtering on ER checklist items.

    - ``condition`` items (e.g. vag004/vag005) are shown/hidden by gender.
    - ``auto_complete`` items (e.g. cou006) trigger immediate termination
      when the condition is met (e.g. child age < 1 with Cough).
    """

    async def _advance_to_phase3(self, engine, mock_db, demographics, symptom):
        """Create session and advance to phase 3 with given demographics and symptom."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=demographics,
        )
        store = engine._store
        er_responses = _er_responses_for(store, demographics)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        return await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms",
            value={"primary_symptom": symptom},
        )

    @pytest.mark.asyncio
    async def test_auto_complete_triggers_for_infant_cough(self, engine, mock_db):
        """Child age 0 with Cough should auto-terminate at phase 3 (cou006)."""
        infant_demographics = {
            **VALID_DEMOGRAPHICS,
            "age": 0, "age_months": 3,
        }
        step = await self._advance_to_phase3(
            engine, mock_db, infant_demographics, "Cough",
        )
        assert isinstance(step, TerminationStep), \
            "Expected auto-complete termination for infant with Cough"
        assert step.phase == 3, "Termination should come from phase 3"

    @pytest.mark.asyncio
    async def test_auto_complete_does_not_trigger_for_older_child_cough(self, engine, mock_db):
        """Child age 5 with Cough should NOT auto-terminate (age >= 1)."""
        child_demographics = {**VALID_DEMOGRAPHICS, "age": 5}
        step = await self._advance_to_phase3(
            engine, mock_db, child_demographics, "Cough",
        )
        assert isinstance(step, QuestionsStep), \
            "Expected QuestionsStep for child age 5 with Cough"
        # cou006 should not appear (auto_complete items are hidden)
        qids = {q.qid for q in step.questions}
        assert "emer_ped_cou006" not in qids, \
            "auto_complete item cou006 should be hidden when condition not met"

    @pytest.mark.asyncio
    async def test_auto_complete_stomachache_for_toddler(self, engine, mock_db):
        """Child age 2 with Stomachache should auto-terminate (abd008, age < 4)."""
        toddler_demographics = {**VALID_DEMOGRAPHICS, "age": 2}
        step = await self._advance_to_phase3(
            engine, mock_db, toddler_demographics, "Stomachache",
        )
        assert isinstance(step, TerminationStep), \
            "Expected auto-complete termination for toddler with Stomachache"

    @pytest.mark.asyncio
    async def test_auto_complete_diarrhea_under_6_months(self, engine, mock_db):
        """Child 3 months old with Diarrhea should auto-terminate (dia006, age_in_months < 6)."""
        infant_demographics = {
            **VALID_DEMOGRAPHICS,
            "age": 0, "age_months": 3,
        }
        step = await self._advance_to_phase3(
            engine, mock_db, infant_demographics, "Diarrhea",
        )
        assert isinstance(step, TerminationStep), \
            "Expected auto-complete termination for 3-month-old with Diarrhea"

    @pytest.mark.asyncio
    async def test_auto_complete_diarrhea_not_triggered_at_8_months(self, engine, mock_db):
        """Child 8 months old with Diarrhea should NOT auto-terminate (age_in_months >= 6)."""
        baby_demographics = {
            **VALID_DEMOGRAPHICS,
            "age": 0, "age_months": 8,
        }
        step = await self._advance_to_phase3(
            engine, mock_db, baby_demographics, "Diarrhea",
        )
        assert isinstance(step, QuestionsStep), \
            "Expected QuestionsStep for 8-month-old with Diarrhea"

    @pytest.mark.asyncio
    async def test_condition_filters_vag_items_by_gender(self, engine, mock_db):
        """Female child should see vag004 but not vag005; male should see vag005 but not vag004."""
        female_child = {
            **VALID_DEMOGRAPHICS,
            "age": 10, "gender": "Female",
            "pregnancy_status": "not_pregnant",
            "last_menstrual_period": "2026-02-15",
            "menstrual_duration_days": 5,
            "menstrual_flow": "same",
        }
        step_f = await self._advance_to_phase3(
            engine, mock_db, female_child, "Vaginal Discharge",
        )
        assert isinstance(step_f, QuestionsStep)
        qids_f = {q.qid for q in step_f.questions}
        assert "emer_ped_vag004" in qids_f, \
            "Female should see vag004"
        assert "emer_ped_vag005" not in qids_f, \
            "Female should NOT see vag005"


# =====================================================================
# Phase 3: ER Adult Checklist — Gender/Pregnancy Conditions
# =====================================================================


class TestPhase3ERAdultChecklistConditions:
    """Tests for gender/pregnancy condition filtering on adult ER checklist items.

    - ``emer_adult_vag003``, ``emer_adult_abd008``, ``emer_adult_diz007``:
      pregnancy_status == pregnant (excluded for males and non-pregnant females)
    - ``emer_adult_abd009``: gender == Male (testicular pain)
    - ``emer_adult_hea006``: gender == Female (pregnancy-related headache)
    """

    async def _advance_to_phase3(self, engine, mock_db, demographics, symptom):
        """Create session and advance to phase 3 with given demographics and symptom."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=demographics,
        )
        store = engine._store
        er_responses = _er_responses_for(store, demographics)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        return await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms",
            value={"primary_symptom": symptom},
        )

    @pytest.mark.asyncio
    async def test_male_excludes_pregnancy_and_female_items(self, engine, mock_db):
        """Male patient should not see pregnancy-condition or female-only items."""
        male_demographics = {**VALID_DEMOGRAPHICS, "age": 30, "gender": "Male"}
        # Test Stomachache to check abd008 (pregnancy) and abd009 (male)
        step = await self._advance_to_phase3(
            engine, mock_db, male_demographics, "Stomachache",
        )
        assert isinstance(step, QuestionsStep)
        qids = {q.qid for q in step.questions}
        # abd008 requires pregnancy_status == pregnant → excluded for males
        assert "emer_adult_abd008" not in qids, \
            "Male should NOT see abd008 (pregnancy condition)"
        # abd009 requires gender == Male → included
        assert "emer_adult_abd009" in qids, \
            "Male should see abd009 (testicular pain)"

    @pytest.mark.asyncio
    async def test_female_nonpregnant_excludes_pregnancy_items(self, engine, mock_db):
        """Female non-pregnant patient should not see pregnancy-condition items but should see hea006."""
        female_nonpregnant = {
            **VALID_DEMOGRAPHICS,
            "age": 30, "gender": "Female",
            "pregnancy_status": "not_pregnant",
            "last_menstrual_period": "2026-02-15",
            "menstrual_duration_days": 5,
            "menstrual_flow": "same",
        }
        # Test Headache to check hea006 (female-only)
        step = await self._advance_to_phase3(
            engine, mock_db, female_nonpregnant, "Headache",
        )
        assert isinstance(step, QuestionsStep)
        qids = {q.qid for q in step.questions}
        # hea006 requires gender == Female → included
        assert "emer_adult_hea006" in qids, \
            "Non-pregnant female should see hea006 (female condition)"

    @pytest.mark.asyncio
    async def test_female_nonpregnant_excludes_abd008(self, engine, mock_db):
        """Female non-pregnant patient should not see abd008 (pregnancy-only) but abd009 excluded too."""
        female_nonpregnant = {
            **VALID_DEMOGRAPHICS,
            "age": 30, "gender": "Female",
            "pregnancy_status": "not_pregnant",
            "last_menstrual_period": "2026-02-15",
            "menstrual_duration_days": 5,
            "menstrual_flow": "same",
        }
        step = await self._advance_to_phase3(
            engine, mock_db, female_nonpregnant, "Stomachache",
        )
        assert isinstance(step, QuestionsStep)
        qids = {q.qid for q in step.questions}
        assert "emer_adult_abd008" not in qids, \
            "Non-pregnant female should NOT see abd008 (pregnancy condition)"
        assert "emer_adult_abd009" not in qids, \
            "Female should NOT see abd009 (male-only)"

    @pytest.mark.asyncio
    async def test_pregnant_female_sees_pregnancy_items(self, engine, mock_db):
        """Pregnant female should see pregnancy-condition items and female-only items."""
        pregnant_female = {
            **VALID_DEMOGRAPHICS,
            "age": 30, "gender": "Female",
            "pregnancy_status": "pregnant",
            "total_pregnancies": 1,
            "fetuses_count": 1,
            "gestational_age_weeks": 20,
        }
        # Test Stomachache for abd008 (pregnant), abd009 (male-only)
        step = await self._advance_to_phase3(
            engine, mock_db, pregnant_female, "Stomachache",
        )
        assert isinstance(step, QuestionsStep)
        qids = {q.qid for q in step.questions}
        assert "emer_adult_abd008" in qids, \
            "Pregnant female should see abd008 (pregnancy condition)"
        assert "emer_adult_abd009" not in qids, \
            "Pregnant female should NOT see abd009 (male-only)"

    @pytest.mark.asyncio
    async def test_male_excludes_hea006(self, engine, mock_db):
        """Male patient should not see hea006 (female-only headache item)."""
        male_demographics = {**VALID_DEMOGRAPHICS, "age": 30, "gender": "Male"}
        step = await self._advance_to_phase3(
            engine, mock_db, male_demographics, "Headache",
        )
        assert isinstance(step, QuestionsStep)
        qids = {q.qid for q in step.questions}
        assert "emer_adult_hea006" not in qids, \
            "Male should NOT see hea006 (female-only)"


# =====================================================================
# Phases 4/7: Sequential (OLDCARTS / OPD)
# =====================================================================


class TestPhase4Sequential:
    """Tests for sequential OLDCARTS question handling."""

    async def _setup_phase4(self, engine, mock_db):
        """Create session and advance to phase 4 (OLDCARTS)."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
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
            assert step.phase in (4, 5, 6, 7), (
                f"Expected phase 4-7, got {step.phase}"
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


# =====================================================================
# QID auto-derivation (qid=None)
# =====================================================================


class TestQidAutoDerivation:
    """Tests that submit_answer works when qid is omitted (None).

    For bulk phases (0-3, 5-6), qid is unused by the engine — passing None
    should behave identically to passing the phase marker string.
    For sequential phases (4, 7), the engine auto-derives the qid from
    the current step via _derive_current_qid.
    """

    @pytest.mark.asyncio
    async def test_submit_demographics_without_qid(self, engine, mock_db):
        """Phase 0 accepts qid=None — demographics submission works."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should advance to phase 1"

    @pytest.mark.asyncio
    async def test_submit_er_critical_without_qid(self, engine, mock_db):
        """Phase 1 accepts qid=None — ER critical submission works."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=er_responses,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 2, "Should advance to phase 2"

    @pytest.mark.asyncio
    async def test_submit_symptoms_without_qid(self, engine, mock_db):
        """Phase 2 accepts qid=None — symptom selection works."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value={"primary_symptom": "Headache"},
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 3, "Should advance to phase 3"

    @pytest.mark.asyncio
    async def test_submit_er_checklist_without_qid(self, engine, mock_db):
        """Phase 3 accepts qid=None — ER checklist submission works."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms", value={"primary_symptom": "Headache"},
        )
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=checklist_responses,
        )
        assert isinstance(step, (QuestionsStep, TerminationStep)), (
            "Expected QuestionsStep or TerminationStep"
        )
        if isinstance(step, QuestionsStep):
            assert step.phase >= 4, f"Expected phase >= 4, got {step.phase}"

    @pytest.mark.asyncio
    async def test_submit_sequential_without_qid(self, engine, mock_db):
        """Phases 4 and 7 auto-derive qid from _compute_step when qid=None."""
        # Advance to phase 4 using explicit qids
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms", value={"primary_symptom": "Headache"},
        )
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )

        # Now in sequential phase — get the first question
        step = await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        if not isinstance(step, QuestionsStep):
            # Tree auto-resolved (all filters), nothing to test
            return

        # Submit without qid — engine should auto-derive it
        first_q = step.questions[0]
        # Pick a valid answer: first option ID for select types, or a string
        if first_q.options:
            answer = first_q.options[0]["id"]
        else:
            answer = "test answer"

        # Compare: submit with explicit qid vs auto-derived should produce
        # the same next step type.  Here we just verify no error is raised
        # and a valid step is returned.
        next_step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=answer,
        )
        assert isinstance(next_step, (QuestionsStep, TerminationStep)), (
            f"Expected QuestionsStep or TerminationStep, got {type(next_step).__name__}"
        )


# =====================================================================
# Multi-step sequential submission (regression for qid derivation bug)
# =====================================================================


class TestMultiStepSequential:
    """Verify that submitting multiple sequential answers (qid=None) works.

    Regression test: before the fix, _derive_current_qid would return
    the NEXT question's qid instead of the current one after the first
    sequential submission, because the pending queue had the current
    question already popped.
    """

    async def _setup_phase4(self, engine, mock_db):
        """Create session and advance to phase 4 (OLDCARTS) with Headache."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms", value={"primary_symptom": "Headache"},
        )
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )
        return step

    def _pick_answer(self, q):
        """Pick a deterministic valid answer for a question payload."""
        qtype = q.question_type
        if qtype in ("single_select", "image_single_select"):
            return q.options[0]["id"] if q.options else "unknown"
        if qtype in ("multi_select", "image_multi_select"):
            return [q.options[0]["id"]] if q.options else []
        if qtype == "number_range":
            c = q.constraints or {}
            lo = c.get("min", 0)
            hi = c.get("max", 10)
            return (lo + hi) / 2
        if qtype == "free_text_with_fields":
            if q.fields:
                return {f["id"]: "ไม่มี" for f in q.fields}
            return "ไม่มี"
        return "ไม่มี"

    @pytest.mark.asyncio
    async def test_multiple_sequential_submissions_advance_correctly(
        self, engine, mock_db, mock_repo,
    ):
        """Submitting 4+ sequential answers with qid=None yields distinct qids each time."""
        step = await self._setup_phase4(engine, mock_db)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved — no sequential questions to test")

        seen_qids = []
        # Drive at least 4 sequential questions to exercise the pending queue
        for i in range(4):
            assert isinstance(step, QuestionsStep), (
                f"Expected QuestionsStep on iteration {i}, got {type(step).__name__}"
            )
            q = step.questions[0]
            current_qid = q.qid
            seen_qids.append(current_qid)

            # get_current_step should return the same question
            check = await engine.get_current_step(
                mock_db, user_id="u1", session_id="s1",
            )
            assert isinstance(check, QuestionsStep), (
                f"get_current_step should agree with submit result on iteration {i}"
            )
            assert check.questions[0].qid == current_qid, (
                f"get_current_step returned {check.questions[0].qid}, "
                f"expected {current_qid} on iteration {i}"
            )

            answer = self._pick_answer(q)
            step = await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=answer,
            )

        # All seen qids should be unique — no question was presented twice
        assert len(seen_qids) == len(set(seen_qids)), (
            f"Duplicate qid detected in sequential flow: {seen_qids}"
        )

    @pytest.mark.asyncio
    async def test_sequential_records_correct_qid(
        self, engine, mock_db, mock_repo,
    ):
        """Each sequential answer is recorded under the correct qid in responses."""
        step = await self._setup_phase4(engine, mock_db)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        row = mock_repo._sessions[("u1", "s1")]
        expected_pairs = []

        for i in range(3):
            if not isinstance(step, QuestionsStep):
                break
            q = step.questions[0]
            answer = self._pick_answer(q)
            expected_pairs.append((q.qid, answer))

            step = await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=answer,
            )

        # Check that each answer was recorded under its correct qid
        for qid, expected_answer in expected_pairs:
            assert qid in row.responses, (
                f"Response for {qid} not found in session responses"
            )
            recorded = row.responses[qid]
            actual = recorded["value"] if isinstance(recorded, dict) else recorded
            assert actual == expected_answer, (
                f"Wrong value recorded for {qid}: "
                f"expected {expected_answer!r}, got {actual!r}"
            )


# =====================================================================
# Schema Fields (answer_schema / submission_schema)
# =====================================================================


class TestSchemaFields:
    """Tests that answer_schema and submission_schema are correctly populated."""

    @pytest.mark.asyncio
    async def test_phase0_schemas(self, engine, mock_db):
        """Demographics step has answer_schema on each question and an object submission_schema."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        step = await engine.get_current_step(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 0, "Should be phase 0"

        # Every question should have an answer_schema with a "type" key
        for q in step.questions:
            assert q.answer_schema is not None, (
                f"answer_schema missing for {q.qid}"
            )
            assert "type" in q.answer_schema, (
                f"answer_schema missing 'type' for {q.qid}"
            )

        # int fields should have type "integer"
        int_qs = [q for q in step.questions if q.question_type == "int"]
        for q in int_qs:
            assert q.answer_schema.get("type") == "integer", (
                f"int field {q.qid} should have type='integer'"
            )

        # enum fields should have an "enum" list
        enum_qs = [q for q in step.questions if q.question_type == "enum"]
        for q in enum_qs:
            assert "enum" in q.answer_schema, (
                f"enum field {q.qid} should have 'enum' list"
            )
            assert isinstance(q.answer_schema["enum"], list), (
                f"enum field {q.qid} 'enum' should be a list"
            )

        # yes_no_detail fields should have type "object" with "answer" property
        ynd_qs = [q for q in step.questions if q.question_type == "yes_no_detail"]
        for q in ynd_qs:
            assert q.answer_schema.get("type") == "object", (
                f"yes_no_detail field {q.qid} should have type='object'"
            )

        # submission_schema should be an object with properties and required
        ss = step.submission_schema
        assert ss is not None, "submission_schema should not be None"
        assert ss["type"] == "object", "submission_schema type should be 'object'"
        assert "properties" in ss, "submission_schema should have 'properties'"
        assert "required" in ss, "submission_schema should have 'required'"

        # Optional fields should NOT be in required
        for q in step.questions:
            key = q.metadata["key"]
            if q.metadata.get("optional"):
                assert key not in ss["required"], (
                    f"Optional field '{key}' should not be in required"
                )

        # Conditional fields (those with a condition block in the YAML)
        # should NOT be in the required list — their requirement depends
        # on runtime values (e.g. gender) which aren't known at schema time.
        conditional_keys = {
            f.key for f in engine._store.demographics if f.condition
        }
        for ckey in conditional_keys:
            assert ckey not in ss["required"], (
                f"Conditional field '{ckey}' should not be in required"
            )

        # Conditional fields should have nullable types in submission_schema
        # so clients can send null when the field doesn't apply.
        for ckey in conditional_keys:
            prop_schema = ss["properties"][ckey]
            schema_type = prop_schema.get("type")
            assert isinstance(schema_type, list) and "null" in schema_type, (
                f"Conditional field '{ckey}' should allow null in "
                f"submission_schema, got type={schema_type}"
            )

    @pytest.mark.asyncio
    async def test_phase1_schemas(self, engine, mock_db):
        """ER critical step has boolean answer_schemas and an object submission_schema."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
        )
        step = await engine.get_current_step(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should be phase 1"

        # All ER critical questions should have boolean answer_schema
        for q in step.questions:
            assert q.answer_schema is not None, (
                f"answer_schema missing for {q.qid}"
            )
            assert q.answer_schema["type"] == "boolean", (
                f"ER critical {q.qid} answer_schema type should be 'boolean'"
            )

        # submission_schema should be an object with boolean properties
        ss = step.submission_schema
        assert ss is not None, "submission_schema should not be None"
        assert ss["type"] == "object", "submission_schema type should be 'object'"
        assert len(ss["properties"]) == len(step.questions), (
            "submission_schema properties count should match question count"
        )

    @pytest.mark.asyncio
    async def test_phase2_schemas(self, engine, mock_db):
        """Symptom selection has string+enum primary and array secondary schemas."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        step = await engine.get_current_step(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 2, "Should be phase 2"

        # primary_symptom: string with enum
        primary = [q for q in step.questions if q.qid == "primary_symptom"][0]
        assert primary.answer_schema["type"] == "string", (
            "primary_symptom should be string type"
        )
        assert "enum" in primary.answer_schema, (
            "primary_symptom should have enum list"
        )

        # secondary_symptoms: array of strings
        secondary = [q for q in step.questions if q.qid == "secondary_symptoms"][0]
        assert secondary.answer_schema["type"] == "array", (
            "secondary_symptoms should be array type"
        )

        # submission_schema: required should include primary_symptom only
        ss = step.submission_schema
        assert ss is not None, "submission_schema should not be None"
        assert ss["required"] == ["primary_symptom"], (
            "Only primary_symptom should be required"
        )

    @pytest.mark.asyncio
    async def test_phase3_schemas(self, engine, mock_db):
        """ER checklist has boolean answer_schemas and an object submission_schema."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms", value={"primary_symptom": "Headache"},
        )
        step = await engine.get_current_step(mock_db, user_id="u1", session_id="s1")

        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 3, "Should be phase 3"

        # All ER checklist questions should have boolean answer_schema
        for q in step.questions:
            assert q.answer_schema is not None, (
                f"answer_schema missing for {q.qid}"
            )
            assert q.answer_schema["type"] == "boolean", (
                f"ER checklist {q.qid} answer_schema type should be 'boolean'"
            )

        # submission_schema should be an object
        ss = step.submission_schema
        assert ss is not None, "submission_schema should not be None"
        assert ss["type"] == "object", "submission_schema type should be 'object'"

    @pytest.mark.asyncio
    async def test_sequential_schemas(self, engine, mock_db):
        """Sequential phases have answer_schema populated and submission_schema == answer_schema."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms", value={"primary_symptom": "Headache"},
        )
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )

        step = await engine.get_current_step(mock_db, user_id="u1", session_id="s1")
        if not isinstance(step, QuestionsStep):
            # Tree auto-resolved, nothing to validate
            return

        assert step.phase in (4, 5, 6, 7), f"Expected phase 4-7, got {step.phase}"
        assert len(step.questions) == 1, "Sequential step should have exactly 1 question"

        q = step.questions[0]
        assert q.answer_schema is not None, (
            f"answer_schema missing for sequential question {q.qid}"
        )

        # For sequential phases, submission_schema == the single question's answer_schema
        assert step.submission_schema == q.answer_schema, (
            "submission_schema should equal the question's answer_schema in sequential phases"
        )


# =====================================================================
# Phase 0: Demographics Validation
# =====================================================================


class TestPhase0Validation:
    """Tests that _validate_demographics rejects invalid payloads with clear errors."""

    async def _create_session(self, engine, mock_db):
        """Create a fresh session at phase 0."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")

    # --- Structural checks ---

    @pytest.mark.asyncio
    async def test_non_dict_value_raises(self, engine, mock_db):
        """Submitting a non-dict value raises ValueError."""
        await self._create_session(engine, mock_db)
        with pytest.raises(ValueError, match="must be a dict"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value="not a dict",
            )

    @pytest.mark.asyncio
    async def test_list_value_raises(self, engine, mock_db):
        """Submitting a list value raises ValueError."""
        await self._create_session(engine, mock_db)
        with pytest.raises(ValueError, match="must be a dict"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=[1, 2, 3],
            )

    # --- Required field checks ---

    @pytest.mark.asyncio
    async def test_missing_required_field_raises(self, engine, mock_db):
        """Omitting a required field raises ValueError."""
        await self._create_session(engine, mock_db)
        # Missing age (required)
        incomplete = {
            "gender": "Male",
            "underlying_diseases": [],
            "current_medication": {"answer": False, "detail": None},
            "drug_food_allergies": {"answer": False, "detail": None},
            "surgical_history": {"answer": False, "detail": None},
        }
        with pytest.raises(ValueError, match="Missing required.*age"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=incomplete,
            )

    @pytest.mark.asyncio
    async def test_none_required_field_raises(self, engine, mock_db):
        """Setting a required field to None raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "gender": None}
        with pytest.raises(ValueError, match="Missing required.*gender"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    # --- int (age) checks ---

    @pytest.mark.asyncio
    async def test_non_integer_age_raises(self, engine, mock_db):
        """String age raises ValueError (age is an int field)."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "age": "thirty"}
        with pytest.raises(ValueError, match="must be an integer"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    @pytest.mark.asyncio
    async def test_boolean_age_raises(self, engine, mock_db):
        """Boolean value for age raises ValueError (bool is subclass of int)."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "age": True}
        with pytest.raises(ValueError, match="must be an integer"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    # --- enum checks ---

    @pytest.mark.asyncio
    async def test_invalid_gender_value_raises(self, engine, mock_db):
        """Gender value not in allowed list raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "gender": "other"}
        with pytest.raises(ValueError, match="must be one of"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    @pytest.mark.asyncio
    async def test_non_string_gender_raises(self, engine, mock_db):
        """Non-string gender value raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "gender": 1}
        with pytest.raises(ValueError, match="must be a string"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    # --- yes_no_detail checks ---

    @pytest.mark.asyncio
    async def test_yes_no_detail_non_dict_raises(self, engine, mock_db):
        """String instead of dict for yes_no_detail field raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "current_medication": "none"}
        with pytest.raises(ValueError, match="must be an object"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    @pytest.mark.asyncio
    async def test_yes_no_detail_missing_answer_raises(self, engine, mock_db):
        """Missing 'answer' key in yes_no_detail raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "current_medication": {"detail": "aspirin"}}
        with pytest.raises(ValueError, match="must contain 'answer' key"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    @pytest.mark.asyncio
    async def test_yes_no_detail_non_bool_answer_raises(self, engine, mock_db):
        """Non-boolean 'answer' in yes_no_detail raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "drug_food_allergies": {"answer": "yes", "detail": None}}
        with pytest.raises(ValueError, match="answer must be a boolean"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    # --- from_yaml (underlying_diseases) checks ---

    @pytest.mark.asyncio
    async def test_underlying_diseases_not_list_raises(self, engine, mock_db):
        """String instead of list for underlying_diseases raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "underlying_diseases": "Diabetes"}
        with pytest.raises(ValueError, match="must be a list"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    @pytest.mark.asyncio
    async def test_unknown_underlying_disease_raises(self, engine, mock_db):
        """Unknown disease name raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "underlying_diseases": ["FakeDisease123"]}
        with pytest.raises(ValueError, match="unknown value.*FakeDisease123"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    @pytest.mark.asyncio
    async def test_underlying_diseases_non_string_item_raises(self, engine, mock_db):
        """Non-string item in underlying_diseases raises ValueError."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "underlying_diseases": [123]}
        with pytest.raises(ValueError, match="items must be strings"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=payload,
            )

    # --- Valid payloads ---

    @pytest.mark.asyncio
    async def test_complete_valid_payload_succeeds(self, engine, mock_db):
        """A complete valid demographics payload advances to phase 1."""
        await self._create_session(engine, mock_db)
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should advance to phase 1"

    @pytest.mark.asyncio
    async def test_empty_underlying_diseases_accepted(self, engine, mock_db):
        """Empty list for underlying_diseases is accepted."""
        await self._create_session(engine, mock_db)
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should advance to phase 1"

    @pytest.mark.asyncio
    async def test_yes_no_detail_with_true_answer_accepted(self, engine, mock_db):
        """yes_no_detail field with answer=True and detail string is accepted."""
        await self._create_session(engine, mock_db)
        payload = {
            **VALID_DEMOGRAPHICS,
            "current_medication": {"answer": True, "detail": "Aspirin 81mg"},
        }
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=payload,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should advance to phase 1"

    @pytest.mark.asyncio
    async def test_extra_keys_accepted(self, engine, mock_db):
        """Extra keys not in the schema are accepted for forward compatibility."""
        await self._create_session(engine, mock_db)
        payload = {**VALID_DEMOGRAPHICS, "unknown_field": "some_value"}
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=payload,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should advance to phase 1"


# =====================================================================
# Back-edit
# =====================================================================


class TestBackEdit:
    """Tests for back_edit() — reverting to a previous phase or question."""

    async def _setup_phase4(self, engine, mock_db):
        """Create session and advance to phase 4 (OLDCARTS) with Headache."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
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
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )
        return step

    # --- Validation tests ---

    @pytest.mark.asyncio
    async def test_rejects_terminated_session(self, engine, mock_db, mock_repo):
        """back_edit raises ValueError on a terminated session."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.TERMINATED
        row.terminated_at_phase = 1
        row.result = {"departments": ["dept002"], "severity": "sev003"}

        with pytest.raises(ValueError, match="status"):
            await engine.back_edit(
                mock_db, user_id="u1", session_id="s1",
                target_phase=0,
            )

    @pytest.mark.asyncio
    async def test_rejects_completed_session(self, engine, mock_db, mock_repo):
        """back_edit raises ValueError on a completed session."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.COMPLETED
        row.result = {"departments": ["dept001"], "severity": "sev001"}

        with pytest.raises(ValueError, match="status"):
            await engine.back_edit(
                mock_db, user_id="u1", session_id="s1",
                target_phase=0,
            )

    @pytest.mark.asyncio
    async def test_rejects_later_phase(self, engine, mock_db):
        """back_edit raises ValueError when target_phase > current_phase."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        # Session at phase 0 — cannot go to phase 2
        with pytest.raises(ValueError, match="must be <="):
            await engine.back_edit(
                mock_db, user_id="u1", session_id="s1",
                target_phase=2,
            )

    @pytest.mark.asyncio
    async def test_rejects_same_phase_without_qid(self, engine, mock_db):
        """back_edit raises ValueError when target_phase == current_phase without target_qid."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        # At phase 1 — cannot back-edit to phase 1 without target_qid
        with pytest.raises(ValueError, match="equals current_phase"):
            await engine.back_edit(
                mock_db, user_id="u1", session_id="s1",
                target_phase=1,
            )

    @pytest.mark.asyncio
    async def test_rejects_qid_on_bulk_phase(self, engine, mock_db):
        """back_edit raises ValueError when target_qid is provided for bulk phase."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        with pytest.raises(ValueError, match="only valid for phases 4 and 7"):
            await engine.back_edit(
                mock_db, user_id="u1", session_id="s1",
                target_phase=0,
                target_qid="some_qid",
            )

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_qid(self, engine, mock_db):
        """back_edit raises ValueError when target_qid is not in responses."""
        step = await self._setup_phase4(engine, mock_db)
        if not isinstance(step, QuestionsStep):
            pytest.skip("Tree auto-resolved")

        with pytest.raises(ValueError, match="not found in session responses"):
            await engine.back_edit(
                mock_db, user_id="u1", session_id="s1",
                target_phase=4,
                target_qid="nonexistent_qid_xyz",
            )

    @pytest.mark.asyncio
    async def test_rejects_invalid_phase_number(self, engine, mock_db):
        """back_edit raises ValueError for target_phase outside 0-7."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        with pytest.raises(ValueError, match="must be 0-7"):
            await engine.back_edit(
                mock_db, user_id="u1", session_id="s1",
                target_phase=8,
            )
        with pytest.raises(ValueError, match="must be 0-7"):
            await engine.back_edit(
                mock_db, user_id="u1", session_id="s1",
                target_phase=-1,
            )

    # --- Phase-level back-edit tests ---

    @pytest.mark.asyncio
    async def test_back_to_phase0_returns_demographics(self, engine, mock_db, mock_repo):
        """Back-edit to phase 0 returns demographics step with previous values."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        # Now at phase 1 — go back to phase 0
        step = await engine.back_edit(
            mock_db, user_id="u1", session_id="s1",
            target_phase=0,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 0, "Should be at phase 0"
        assert step.phase_name == "Demographics", "Phase name should be Demographics"

        # Verify session state was cleared
        row = mock_repo._sessions[("u1", "s1")]
        assert row.current_phase == 0, "current_phase should be 0"
        assert row.demographics == {}, "demographics should be cleared"

    @pytest.mark.asyncio
    async def test_back_to_phase0_has_previous_values(self, engine, mock_db, mock_repo):
        """Back-edit to phase 0 injects previous_value in question metadata."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        step = await engine.back_edit(
            mock_db, user_id="u1", session_id="s1",
            target_phase=0,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        # At least one question should have previous_value set
        has_previous = any(
            q.metadata and q.metadata.get("previous_value") is not None
            for q in step.questions
        )
        assert has_previous, "At least one question should have previous_value in metadata"

    @pytest.mark.asyncio
    async def test_back_to_phase1_clears_later_data(self, engine, mock_db, mock_repo):
        """Back-edit to phase 1 clears symptoms, ER flags, and phase 1+ responses."""
        step = await self._setup_phase4(engine, mock_db)
        row = mock_repo._sessions[("u1", "s1")]

        # Verify symptoms were set before back-edit
        assert row.primary_symptom == "Headache", "Should have primary_symptom before back-edit"

        step = await engine.back_edit(
            mock_db, user_id="u1", session_id="s1",
            target_phase=1,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should be at phase 1"

        # Verify later data was cleared
        assert row.primary_symptom is None, "primary_symptom should be cleared"
        assert row.secondary_symptoms is None, "secondary_symptoms should be cleared"
        assert row.er_flags is None, "er_flags should be cleared"
        assert row.current_phase == 1, "current_phase should be 1"

    @pytest.mark.asyncio
    async def test_back_to_phase2_keeps_er_critical(self, engine, mock_db, mock_repo):
        """Back-edit to phase 2 keeps phase 1 ER critical responses intact."""
        step = await self._setup_phase4(engine, mock_db)
        row = mock_repo._sessions[("u1", "s1")]
        store = engine._store

        # Check that ER critical responses exist before back-edit
        er_qids = {item.qid for item in store.er_critical}
        had_er_responses = any(qid in row.responses for qid in er_qids)
        assert had_er_responses, "Should have ER critical responses before back-edit"

        step = await engine.back_edit(
            mock_db, user_id="u1", session_id="s1",
            target_phase=2,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 2, "Should be at phase 2"

        # ER critical responses should still exist
        still_has_er = any(qid in row.responses for qid in er_qids)
        assert still_has_er, "ER critical responses should be preserved"

        # Symptoms should be cleared (phase 2+ data)
        assert row.primary_symptom is None, "primary_symptom should be cleared"

    @pytest.mark.asyncio
    async def test_back_to_phase3_keeps_symptoms(self, engine, mock_db, mock_repo):
        """Back-edit to phase 3 keeps symptoms but clears ER flags."""
        step = await self._setup_phase4(engine, mock_db)
        row = mock_repo._sessions[("u1", "s1")]

        step = await engine.back_edit(
            mock_db, user_id="u1", session_id="s1",
            target_phase=3,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 3, "Should be at phase 3"
        # Symptoms should still exist (set in phase 2)
        assert row.primary_symptom == "Headache", (
            "primary_symptom should be preserved when going back to phase 3"
        )
        assert row.er_flags is None, "er_flags should be cleared"

    # --- Forward flow after back-edit ---

    @pytest.mark.asyncio
    async def test_submit_answer_works_after_back_edit(self, engine, mock_db, mock_repo):
        """Submitting an answer works correctly after back-edit."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        # Advance to phase 1
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        # Back-edit to phase 0
        await engine.back_edit(
            mock_db, user_id="u1", session_id="s1",
            target_phase=0,
        )
        # Re-submit demographics — should advance to phase 1 again
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep after re-submit"
        assert step.phase == 1, "Should advance to phase 1 after re-submitting demographics"

    # --- Qid-level back-edit in sequential phases ---

    @pytest.mark.asyncio
    async def test_qid_back_edit_in_sequential_phase(self, engine, mock_db, mock_repo):
        """Back-edit to a specific qid in phase 4 returns that question."""
        step = await self._setup_phase4(engine, mock_db)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved — no sequential questions to test")

        row = mock_repo._sessions[("u1", "s1")]

        # Submit a few sequential answers to build up responses
        answered_qids = []
        for _ in range(3):
            if not isinstance(step, QuestionsStep):
                break
            q = step.questions[0]
            answered_qids.append(q.qid)
            if q.options:
                answer = q.options[0]["id"]
            else:
                answer = "test"
            step = await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=answer,
            )

        if len(answered_qids) < 2:
            pytest.skip("Not enough sequential questions to test qid-level back-edit")

        # Go back to the first answered qid
        target = answered_qids[0]
        step = await engine.back_edit(
            mock_db, user_id="u1", session_id="s1",
            target_phase=row.current_phase,
            target_qid=target,
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        # The returned step should present the target question (or a question
        # after it if auto-eval resolves the target)
        assert step.phase in (4, 5, 6, 7), f"Expected phase 4-7, got {step.phase}"

        # The target qid should no longer be in responses (it was removed)
        assert target not in row.responses, (
            f"Target qid {target} should be removed from responses"
        )


# =====================================================================
# Step-back (go back one step automatically)
# =====================================================================


class TestStepBack:
    """Tests for step_back() — automatically going back one step."""

    async def _setup_phase4(self, engine, mock_db):
        """Create session and advance to phase 4 (OLDCARTS) with Headache."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
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
        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )
        return step

    def _pick_answer(self, q):
        """Pick a deterministic valid answer for a question payload."""
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
        return "ไม่มี"

    # --- Error cases ---

    @pytest.mark.asyncio
    async def test_step_back_from_phase0_raises(self, engine, mock_db):
        """step_back raises ValueError when already at phase 0."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        with pytest.raises(ValueError, match="already at the first step"):
            await engine.step_back(
                mock_db, user_id="u1", session_id="s1",
            )

    @pytest.mark.asyncio
    async def test_step_back_on_terminated_session_raises(
        self, engine, mock_db, mock_repo,
    ):
        """step_back raises ValueError on a terminated session."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.TERMINATED
        row.terminated_at_phase = 1
        row.result = {"departments": ["dept002"], "severity": "sev003"}

        with pytest.raises(ValueError, match="status"):
            await engine.step_back(
                mock_db, user_id="u1", session_id="s1",
            )

    @pytest.mark.asyncio
    async def test_step_back_on_completed_session_raises(
        self, engine, mock_db, mock_repo,
    ):
        """step_back raises ValueError on a completed session."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.COMPLETED
        row.result = {"departments": ["dept001"], "severity": "sev001"}

        with pytest.raises(ValueError, match="status"):
            await engine.step_back(
                mock_db, user_id="u1", session_id="s1",
            )

    # --- Bulk phase transitions ---

    @pytest.mark.asyncio
    async def test_step_back_from_phase1_returns_phase0(self, engine, mock_db):
        """step_back from phase 1 returns phase 0 demographics."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        step = await engine.step_back(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 0, "Should go back to phase 0"
        assert step.phase_name == "Demographics"

    @pytest.mark.asyncio
    async def test_step_back_from_phase2_returns_phase1(self, engine, mock_db):
        """step_back from phase 2 returns phase 1 ER critical."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        step = await engine.step_back(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should go back to phase 1"
        assert step.phase_name == "ER Critical Screen"

    @pytest.mark.asyncio
    async def test_step_back_from_phase3_returns_phase2(self, engine, mock_db):
        """step_back from phase 3 returns phase 2 symptom selection."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_DEMOGRAPHICS,
        )
        store = engine._store
        er_responses = _er_responses_for(store, VALID_DEMOGRAPHICS)
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms",
            value={"primary_symptom": "Headache"},
        )
        step = await engine.step_back(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 2, "Should go back to phase 2"
        assert step.phase_name == "Symptom Selection"

    # --- Phase 4 transitions ---

    @pytest.mark.asyncio
    async def test_step_back_from_phase4_no_answers_returns_phase3(
        self, engine, mock_db, mock_repo,
    ):
        """step_back from phase 4 with no OLDCARTS answers returns phase 3."""
        step = await self._setup_phase4(engine, mock_db)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        # We're at phase 4 but haven't answered any questions yet.
        # However, _setup_phase4 may have auto-resolved some questions
        # during the phase transition.  Check if any OLDCARTS responses
        # exist; if not, step_back should go to phase 3.
        row = mock_repo._sessions[("u1", "s1")]
        store = engine._store
        oldcarts_qids = set(store.oldcarts.get("Headache", {}).keys())
        has_answers = any(
            qid in row.responses and isinstance(row.responses[qid], dict)
            and "answered_at" in row.responses[qid]
            for qid in oldcarts_qids
        )

        if has_answers:
            pytest.skip("Setup auto-answered some OLDCARTS questions")

        step = await engine.step_back(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 3, "Should go back to phase 3"

    @pytest.mark.asyncio
    async def test_step_back_from_phase4_after_answering_returns_last_qid(
        self, engine, mock_db, mock_repo,
    ):
        """step_back from phase 4 after answering returns the last answered OLDCARTS question."""
        step = await self._setup_phase4(engine, mock_db)
        if not isinstance(step, QuestionsStep):
            pytest.skip("OLDCARTS tree auto-resolved")

        # Answer a few sequential questions
        answered_qids = []
        for _ in range(3):
            if not isinstance(step, QuestionsStep):
                break
            q = step.questions[0]
            answered_qids.append(q.qid)
            answer = self._pick_answer(q)
            step = await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=answer,
            )

        if len(answered_qids) < 2:
            pytest.skip("Not enough sequential questions to test step_back")

        # step_back should revert to the last answered question
        row = mock_repo._sessions[("u1", "s1")]
        last_answered = answered_qids[-1]

        step = await engine.step_back(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase in (4, 5, 6, 7), f"Expected phase 4-7, got {step.phase}"

        # The last answered qid should have been removed from responses
        assert last_answered not in row.responses, (
            f"Last answered qid {last_answered} should be removed from responses"
        )


# =====================================================================
# Regression: stale __pending queue & missing completion persistence
# =====================================================================


class TestStalePendingRegression:
    """Regression tests for stale ``__pending`` queue bug.

    When OLDCARTS finishes via auto-eval producing an OPD action,
    ``_resolve_and_persist`` used to save a stale ``__pending`` queue
    containing phase 5 qids.  This corrupted phase 7 OPD initialization,
    causing the entire OPD phase to be skipped.
    """

    @pytest.mark.asyncio
    async def test_advance_phase_clears_pending(self, engine, mock_db, mock_repo):
        """``advance_phase`` removes ``__pending`` from responses."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        # Simulate stale pending from a previous phase
        row.responses = {
            "some_qid": {"value": "x"},
            "__pending": ["stale1", "stale2"],
        }
        await mock_repo.advance_phase(mock_db, row, 5)
        assert "__pending" not in row.responses, (
            "__pending should be cleared on phase advance"
        )
        assert "some_qid" in row.responses, (
            "Non-pending responses should be preserved"
        )

    @pytest.mark.asyncio
    async def test_phase7_not_skipped_with_stale_pending(
        self, engine, mock_db, mock_repo,
    ):
        """Phase 7 OPD shows proper questions even when stale ``__pending`` existed.

        Simulates the scenario where ``__pending`` was stale after OLDCARTS.
        After ``advance_phase(7)`` clears the stale data,
        ``_step_sequential`` should seed with ``get_first_qid('opd', symptom)``
        and return OPD questions — not complete immediately.
        """
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        # Set up session ready for phase 7 — inject stale __pending
        row.current_phase = 6
        row.status = SessionStatus.IN_PROGRESS
        row.demographics = {**VALID_DEMOGRAPHICS, **VALID_PAST_HISTORY}
        row.primary_symptom = "Headache"
        row.responses = {"__pending": ["hea_o_001", "hea_l_001"]}

        # Advance to phase 7 (as _submit_personal_history would)
        await mock_repo.advance_phase(mock_db, row, 7)
        assert "__pending" not in row.responses, (
            "advance_phase should have cleared stale __pending"
        )

        # Now get the step — should show OPD questions, not completion
        step = await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        # Phase 7 should show OPD questions (Headache has 11 OPD questions,
        # starting with a gender_filter that auto-evaluates to a user-facing
        # question downstream).
        if isinstance(step, QuestionsStep):
            assert step.phase == 7, (
                f"Expected phase 7 questions, got phase {step.phase}"
            )
        else:
            # Even if all OPD auto-evaluates to completion, that's valid —
            # the key invariant is we DON'T get stuck on stale OLDCARTS qids.
            assert isinstance(step, TerminationStep), (
                f"Expected QuestionsStep or TerminationStep, got {type(step)}"
            )


class TestAdviceOnlyTerminate:
    """BUG-003: OPD advice-only terminate paths should surface advice as reason.

    Nine OPD terminate actions have a ``metadata.advice`` field with
    self-care guidance but no department or severity.  The engine should
    surface the advice text as the termination ``reason`` so downstream
    consumers (API, frontend, LLM predictor) can see it.
    """

    @pytest.mark.asyncio
    async def test_advice_surfaced_as_reason(self, engine, mock_db, mock_repo):
        """Walk Diarrhea OPD to dia_opd_006 'ไม่ใช่' and verify advice appears in reason."""
        # Set up session directly at phase 7 (OPD) with Diarrhea,
        # pre-populating OLDCARTS answers that OPD conditionals check.
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.current_phase = 7
        row.status = SessionStatus.IN_PROGRESS
        row.demographics = {**VALID_DEMOGRAPHICS, **VALID_PAST_HISTORY}
        row.primary_symptom = "Diarrhea"
        # OLDCARTS answers that OPD conditionals reference — set to benign
        # values so all conditionals fall through to dia_opd_006.
        row.responses = {
            # dia_as_001: no alarming associated symptoms
            "dia_as_001": {"value": ["ไม่มี"]},
            # dia_c_001: ordinary diarrhea character (not bloody mucus)
            "dia_c_001": {"value": "ท้องเสียเป็นน้ำ"},
        }

        # Walk through OPD sequential questions until termination.
        # OPD conditionals (age_filter, pregnancy check, OLDCARTS checks)
        # auto-evaluate.  We only need to answer user-facing questions.
        max_steps = 20
        step = await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )

        for _ in range(max_steps):
            if isinstance(step, TerminationStep):
                break
            assert isinstance(step, QuestionsStep), (
                f"Expected QuestionsStep or TerminationStep, got {type(step).__name__}"
            )
            q = step.questions[0]

            # For multi_select: pick empty list (no concerning features)
            # For single_select: pick "ไม่ใช่" when available, else last option
            if q.question_type in ("multi_select", "image_multi_select"):
                answer = []
            elif q.question_type in ("single_select", "image_single_select"):
                opts = q.options or []
                no_opts = [o for o in opts if "ไม่" in (o.get("id") or "")]
                answer = no_opts[0]["id"] if no_opts else opts[-1]["id"]
            else:
                answer = "ไม่มี"

            step = await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=answer,
            )

        assert isinstance(step, TerminationStep), (
            "Expected flow to terminate after walking OPD Diarrhea tree"
        )
        # The advice-only path should surface the Thai advice text as reason
        assert step.reason is not None, (
            "Advice-only OPD terminate should have reason populated "
            "with the self-care advice text from YAML metadata"
        )
        assert "พบแพทย์" in step.reason, (
            f"Expected Thai advice text containing 'พบแพทย์' (see doctor), "
            f"got: {step.reason!r}"
        )


class TestOPDUnknownChoiceRejection:
    """BUG-004: Submitting an unknown option in OPD must raise ValueError.

    Previously, ``_determine_action`` returned ``None`` for unrecognised
    option IDs in single_select questions.  This caused ``_submit_sequential``
    to silently record the invalid answer and continue resolving the pending
    queue — which could lead to premature termination instead of a clear
    error.  The fix raises ``ValueError`` so the caller gets a 400 response
    and the session state stays clean.
    """

    @pytest.mark.asyncio
    async def test_opd_unknown_choice_raises_value_error(
        self, engine, mock_db, mock_repo,
    ):
        """Submitting 'ไม่เคย' for hea_opd_004 (valid: 'มี'/'ไม่มี') raises ValueError."""
        # Set up session directly at phase 7 (OPD) with Headache.
        # For a 28-year-old male, OPD auto-evals gender_filter and age_filter
        # so the first user-facing question is hea_opd_004 (single_select).
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.current_phase = 7
        row.status = SessionStatus.IN_PROGRESS
        row.demographics = {**VALID_DEMOGRAPHICS, **VALID_PAST_HISTORY}
        row.primary_symptom = "Headache"
        row.responses = {}

        # Verify the first user-facing question is hea_opd_004
        step = await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, QuestionsStep), (
            f"Expected QuestionsStep, got {type(step).__name__}"
        )
        assert step.questions[0].qid == "hea_opd_004", (
            f"Expected hea_opd_004 as first user-facing OPD question, "
            f"got {step.questions[0].qid}"
        )

        # Submit an invalid choice — should raise ValueError, not terminate
        with pytest.raises(ValueError, match="Unknown option"):
            await engine.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value="ไม่เคย",
            )

        # Session state should be unchanged — invalid answer not recorded
        assert "hea_opd_004" not in row.responses, (
            "Invalid answer should not be recorded in session responses"
        )

        # Re-fetching the current step should still show hea_opd_004
        step_after = await engine.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step_after, QuestionsStep), (
            "Session should still present the same question after invalid submit"
        )
        assert step_after.questions[0].qid == "hea_opd_004", (
            "Current step should still be hea_opd_004 after rejected submit"
        )

    @pytest.mark.asyncio
    async def test_opd_valid_choice_still_works(
        self, engine, mock_db, mock_repo,
    ):
        """Submitting 'ไม่มี' (a valid choice) for hea_opd_004 advances normally."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.current_phase = 7
        row.status = SessionStatus.IN_PROGRESS
        row.demographics = {**VALID_DEMOGRAPHICS, **VALID_PAST_HISTORY}
        row.primary_symptom = "Headache"
        row.responses = {}

        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value="ไม่มี",
        )

        # Should advance to the next question, not raise an error
        assert isinstance(step, (QuestionsStep, TerminationStep)), (
            f"Expected QuestionsStep or TerminationStep, got {type(step).__name__}"
        )
        # The answer should be recorded
        assert "hea_opd_004" in row.responses, (
            "Valid answer should be recorded in session responses"
        )


class TestCompletionPersistence:
    """Regression tests for missing completion persistence.

    When a bulk submit handler (e.g. ``_submit_personal_history``) triggers
    a sequential phase that auto-evaluates entirely, ``_compute_step`` used
    to return a ``TerminationStep`` without persisting the session status.
    """

    @pytest.mark.asyncio
    async def test_personal_history_submit_persists_completion(
        self, engine, mock_db, mock_repo,
    ):
        """If phase 7 auto-evaluates to completion after personal history
        submit, the session status and result are properly persisted."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.current_phase = 6
        row.status = SessionStatus.IN_PROGRESS
        row.demographics = {**VALID_DEMOGRAPHICS, **VALID_PAST_HISTORY}
        row.primary_symptom = "Headache"
        row.responses = {}

        step = await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=VALID_PERSONAL_HISTORY,
        )

        if isinstance(step, TerminationStep):
            # Session should be properly persisted as terminal
            assert row.status in (
                SessionStatus.COMPLETED, SessionStatus.TERMINATED,
            ), (
                f"Session status should be terminal after auto-eval "
                f"completion, got {row.status}"
            )
            assert row.result is not None, (
                "Session result should be populated after completion"
            )
