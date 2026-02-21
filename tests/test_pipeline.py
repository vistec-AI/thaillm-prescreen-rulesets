"""PrescreenPipeline tests with mocked DB layer, generator, and predictor.

Reuses the MockSessionRow/MockRepository from test_engine.py and adds mock
implementations of QuestionGenerator and PredictionModule to test the full
pipeline orchestration without a real database or external services.

Test scenarios:
  - Rule-based proxy: pipeline delegates to engine during rule_based stage
  - Early termination: ER positive → PipelineResult with empty DDx
  - Normal completion → LLM questions generated
  - Normal completion → no questions from generator → direct prediction
  - LLM answer submission → prediction runs → PipelineResult with diagnoses
  - Stage guards: wrong-stage calls raise ValueError
  - Done stage: get_current_step returns cached PipelineResult
  - No generator/predictor: graceful handling when either is None
  - QAPair building: correct extraction from session data
"""

from unittest.mock import AsyncMock

import pytest

from prescreen_db.models.enums import PipelineStage, SessionStatus
from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.interfaces import PredictionModule, QuestionGenerator
from prescreen_rulesets.models.pipeline import (
    DiagnosisResult,
    GeneratedQuestions,
    LLMAnswer,
    LLMQuestionsStep,
    PipelineResult,
    PredictionResult,
    QAPair,
)
from prescreen_rulesets.models.session import QuestionsStep, TerminationStep
from prescreen_rulesets.pipeline import PrescreenPipeline
from prescreen_rulesets.ruleset import RulesetStore

# Import mock infrastructure from test_engine
from test_engine import MockRepository, MockSessionRow


# =====================================================================
# Mock generator and predictor
# =====================================================================


class MockQuestionGenerator(QuestionGenerator):
    """In-memory QuestionGenerator that returns configurable questions."""

    def __init__(self, questions: list[str] | None = None):
        self._questions = questions if questions is not None else [
            "อาการปวดรุนแรงแค่ไหน?",
            "มีอาการคลื่นไส้ร่วมด้วยไหม?",
        ]

    async def generate(self, qa_pairs: list[QAPair]) -> GeneratedQuestions:
        """Return preconfigured questions."""
        return GeneratedQuestions(questions=self._questions)


class MockPredictionModule(PredictionModule):
    """In-memory PredictionModule that returns configurable predictions."""

    def __init__(
        self,
        diagnoses: list[DiagnosisResult] | None = None,
        departments: list[str] | None = None,
        severity: str | None = None,
    ):
        self._diagnoses = diagnoses if diagnoses is not None else [
            DiagnosisResult(disease_id="d001", confidence=0.85),
            DiagnosisResult(disease_id="d003", confidence=0.45),
        ]
        self._departments = departments or []
        self._severity = severity

    async def predict(self, qa_pairs: list[QAPair]) -> PredictionResult:
        """Return preconfigured prediction."""
        return PredictionResult(
            diagnoses=self._diagnoses,
            departments=self._departments,
            severity=self._severity,
        )


class EmptyQuestionGenerator(QuestionGenerator):
    """Generator that returns no follow-up questions."""

    async def generate(self, qa_pairs: list[QAPair]) -> GeneratedQuestions:
        return GeneratedQuestions(questions=[])


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
def mock_db():
    """AsyncMock standing in for AsyncSession — flush/commit are no-ops."""
    return AsyncMock()


@pytest.fixture
def engine(store, mock_repo):
    """PrescreenEngine with mocked repository."""
    eng = PrescreenEngine(store)
    eng._repo = mock_repo
    return eng


@pytest.fixture
def mock_generator():
    """MockQuestionGenerator with default questions."""
    return MockQuestionGenerator()


@pytest.fixture
def mock_predictor():
    """MockPredictionModule with default predictions."""
    return MockPredictionModule()


@pytest.fixture
def pipeline(engine, store, mock_repo, mock_generator, mock_predictor):
    """PrescreenPipeline with mocked engine, generator, and predictor."""
    p = PrescreenPipeline(
        engine, store,
        generator=mock_generator,
        predictor=mock_predictor,
    )
    p._repo = mock_repo
    return p


@pytest.fixture
def pipeline_no_generator(engine, store, mock_repo, mock_predictor):
    """PrescreenPipeline with no generator (skip LLM questioning)."""
    p = PrescreenPipeline(engine, store, predictor=mock_predictor)
    p._repo = mock_repo
    return p


@pytest.fixture
def pipeline_no_predictor(engine, store, mock_repo, mock_generator):
    """PrescreenPipeline with no predictor."""
    p = PrescreenPipeline(engine, store, generator=mock_generator)
    p._repo = mock_repo
    return p


@pytest.fixture
def pipeline_bare(engine, store, mock_repo):
    """PrescreenPipeline with no generator and no predictor."""
    p = PrescreenPipeline(engine, store)
    p._repo = mock_repo
    return p


# =====================================================================
# Helper: advance session through rule-based phases
# =====================================================================


async def _advance_to_phase(engine, mock_db, phase: int):
    """Drive a session through the rule-based flow to the given phase.

    Creates a session and submits answers to reach the specified phase.
    Returns the last step result.
    """
    store = engine._store
    await engine.create_session(mock_db, user_id="u1", session_id="s1")

    if phase >= 1:
        # Phase 0 → 1: submit demographics
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value={"gender": "Male", "age": 30},
        )

    if phase >= 2:
        # Phase 1 → 2: all-negative ER critical
        er_responses = {item.qid: False for item in store.er_critical}
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )

    if phase >= 3:
        # Phase 2 → 3: select Headache
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms",
            value={"primary_symptom": "Headache"},
        )

    if phase >= 4:
        # Phase 3 → 4: all-negative ER checklist
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        await engine.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )


# =====================================================================
# Tests: Rule-based proxy
# =====================================================================


class TestRuleBasedProxy:
    """Pipeline delegates to engine during the rule_based stage."""

    @pytest.mark.asyncio
    async def test_create_session_delegates_to_engine(self, pipeline, mock_db):
        """create_session proxies to the engine and returns SessionInfo."""
        info = await pipeline.create_session(
            mock_db, user_id="u1", session_id="s1",
        )
        assert info.user_id == "u1", "user_id mismatch"
        assert info.session_id == "s1", "session_id mismatch"
        assert info.status == "created", "New session should be 'created'"

    @pytest.mark.asyncio
    async def test_get_current_step_delegates_during_rule_based(
        self, pipeline, engine, mock_db,
    ):
        """get_current_step delegates to engine when pipeline_stage is rule_based."""
        await pipeline.create_session(mock_db, user_id="u1", session_id="s1")
        step = await pipeline.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep from engine"
        assert step.phase == 0, "Should be demographics phase"

    @pytest.mark.asyncio
    async def test_submit_answer_delegates_during_rule_based(
        self, pipeline, mock_db,
    ):
        """submit_answer delegates to engine for rule-based questions."""
        await pipeline.create_session(mock_db, user_id="u1", session_id="s1")
        step = await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value={"gender": "Male", "age": 30},
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should advance to phase 1"


# =====================================================================
# Tests: Early termination
# =====================================================================


class TestEarlyTermination:
    """Pipeline handles ER early termination correctly."""

    @pytest.mark.asyncio
    async def test_er_critical_positive_returns_pipeline_result(
        self, pipeline, engine, mock_db,
    ):
        """ER critical positive → PipelineResult with empty DDx, terminated_early."""
        store = engine._store
        await pipeline.create_session(mock_db, user_id="u1", session_id="s1")

        # Submit demographics to reach phase 1
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value={"gender": "Male", "age": 30},
        )

        # Submit ER critical with one positive
        er_responses = {item.qid: False for item in store.er_critical}
        er_responses[store.er_critical[0].qid] = True

        result = await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        assert isinstance(result, PipelineResult), (
            f"Expected PipelineResult, got {type(result).__name__}"
        )
        assert result.terminated_early is True, "Should be terminated_early"
        assert result.diagnoses == [], "Early termination should have empty DDx"
        assert len(result.departments) > 0, "Should have at least one department"

    @pytest.mark.asyncio
    async def test_er_checklist_positive_returns_pipeline_result(
        self, pipeline, engine, mock_db,
    ):
        """ER checklist positive → PipelineResult with empty DDx."""
        store = engine._store
        await pipeline.create_session(mock_db, user_id="u1", session_id="s1")

        # Advance through phases 0-2
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value={"gender": "Male", "age": 30},
        )
        er_responses = {item.qid: False for item in store.er_critical}
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms", value={"primary_symptom": "Headache"},
        )

        # Submit ER checklist with one positive
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        checklist_responses[checklist_items[0].qid] = True

        result = await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )
        assert isinstance(result, PipelineResult), (
            f"Expected PipelineResult, got {type(result).__name__}"
        )
        assert result.terminated_early is True, "Should be terminated_early"
        assert result.diagnoses == [], "Early termination should have empty DDx"


# =====================================================================
# Tests: Normal completion with LLM questions
# =====================================================================


class TestNormalCompletionWithLLM:
    """Pipeline handles normal completion → LLM question generation."""

    @pytest.mark.asyncio
    async def test_completion_generates_llm_questions(
        self, pipeline, engine, mock_db, mock_repo,
    ):
        """Normal completion → generator called → LLMQuestionsStep returned."""
        # Manually set up a completed session (simulating engine finishing all phases)
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        # Simulate engine completion
        row.status = SessionStatus.COMPLETED
        row.current_phase = 5
        row.primary_symptom = "Headache"
        row.demographics = {"gender": "Male", "age": 30}
        row.result = {
            "departments": ["dept001"],
            "severity": "sev001",
            "reason": "OPD routing",
        }

        # Create a TerminationStep that the engine would have returned
        term_step = TerminationStep(
            type="completed",
            phase=5,
            departments=[{"id": "dept001", "name": "Internal Medicine"}],
            severity={"id": "sev001", "name": "Observe at Home"},
            reason="OPD routing",
        )

        # Call the handler directly
        result = await pipeline._handle_rule_based_end(mock_db, row, term_step)

        assert isinstance(result, LLMQuestionsStep), (
            f"Expected LLMQuestionsStep, got {type(result).__name__}"
        )
        assert len(result.questions) == 2, "Should have 2 LLM questions"
        assert row.pipeline_stage == PipelineStage.LLM_QUESTIONING.value, (
            "pipeline_stage should be llm_questioning"
        )
        assert row.llm_questions is not None, "llm_questions should be stored"

    @pytest.mark.asyncio
    async def test_get_current_step_returns_llm_questions(
        self, pipeline, mock_repo, mock_db, engine,
    ):
        """get_current_step returns LLMQuestionsStep when in llm_questioning."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        # Manually transition to llm_questioning
        row.pipeline_stage = PipelineStage.LLM_QUESTIONING.value
        row.llm_questions = ["Question 1?", "Question 2?"]

        step = await pipeline.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, LLMQuestionsStep), "Expected LLMQuestionsStep"
        assert step.questions == ["Question 1?", "Question 2?"]


# =====================================================================
# Tests: Normal completion without LLM questions
# =====================================================================


class TestNormalCompletionNoQuestions:
    """Pipeline handles generator returning 0 questions → direct prediction."""

    @pytest.mark.asyncio
    async def test_empty_questions_skips_to_prediction(
        self, engine, store, mock_repo, mock_predictor, mock_db,
    ):
        """Generator returns 0 questions → prediction runs directly."""
        # Use empty generator
        p = PrescreenPipeline(
            engine, store,
            generator=EmptyQuestionGenerator(),
            predictor=mock_predictor,
        )
        p._repo = mock_repo

        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        # Simulate engine completion
        row.status = SessionStatus.COMPLETED
        row.current_phase = 5
        row.primary_symptom = "Headache"
        row.demographics = {"gender": "Male", "age": 30}
        row.result = {
            "departments": ["dept001"],
            "severity": "sev001",
            "reason": "OPD routing",
        }

        term_step = TerminationStep(
            type="completed", phase=5,
            departments=[], severity=None, reason="OPD routing",
        )

        result = await p._handle_rule_based_end(mock_db, row, term_step)

        assert isinstance(result, PipelineResult), (
            f"Expected PipelineResult, got {type(result).__name__}"
        )
        assert row.pipeline_stage == PipelineStage.DONE.value, (
            "pipeline_stage should be done"
        )
        # Prediction should have populated diagnoses
        assert len(result.diagnoses) == 2, "Should have 2 diagnoses from predictor"


# =====================================================================
# Tests: LLM answer submission
# =====================================================================


class TestLLMAnswerSubmission:
    """Pipeline handles LLM answer submission → prediction → PipelineResult."""

    @pytest.mark.asyncio
    async def test_submit_llm_answers_runs_prediction(
        self, pipeline, engine, mock_repo, mock_db,
    ):
        """Submitting LLM answers stores them and runs prediction."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        # Set up session in llm_questioning state
        row.status = SessionStatus.COMPLETED
        row.current_phase = 5
        row.primary_symptom = "Headache"
        row.demographics = {"gender": "Male", "age": 30}
        row.pipeline_stage = PipelineStage.LLM_QUESTIONING.value
        row.llm_questions = ["Q1?", "Q2?"]
        row.result = {
            "departments": ["dept001"],
            "severity": "sev001",
            "reason": "OPD routing",
        }

        answers = [
            LLMAnswer(question="Q1?", answer="ปวดมาก"),
            LLMAnswer(question="Q2?", answer="ไม่คลื่นไส้"),
        ]

        result = await pipeline.submit_llm_answers(
            mock_db, user_id="u1", session_id="s1",
            answers=answers,
        )

        assert isinstance(result, PipelineResult), (
            f"Expected PipelineResult, got {type(result).__name__}"
        )
        assert result.type == "pipeline_result"
        assert row.pipeline_stage == PipelineStage.DONE.value
        assert row.llm_responses is not None, "llm_responses should be stored"
        assert len(row.llm_responses) == 2, "Should have 2 LLM responses"
        assert len(result.diagnoses) == 2, "Should have diagnoses from predictor"


# =====================================================================
# Tests: Stage guards
# =====================================================================


class TestStageGuards:
    """Pipeline rejects calls in the wrong stage."""

    @pytest.mark.asyncio
    async def test_submit_answer_rejects_if_not_rule_based(
        self, pipeline, engine, mock_repo, mock_db,
    ):
        """submit_answer raises ValueError if pipeline_stage is not rule_based."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.pipeline_stage = PipelineStage.LLM_QUESTIONING.value

        with pytest.raises(ValueError, match="rule_based"):
            await pipeline.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                qid="demographics", value={},
            )

    @pytest.mark.asyncio
    async def test_submit_llm_answers_rejects_if_not_llm_questioning(
        self, pipeline, engine, mock_repo, mock_db,
    ):
        """submit_llm_answers raises ValueError if not in llm_questioning."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")

        with pytest.raises(ValueError, match="llm_questioning"):
            await pipeline.submit_llm_answers(
                mock_db, user_id="u1", session_id="s1",
                answers=[LLMAnswer(question="Q?", answer="A")],
            )


# =====================================================================
# Tests: Done stage
# =====================================================================


class TestDoneStage:
    """Pipeline returns cached result when in done stage."""

    @pytest.mark.asyncio
    async def test_get_current_step_returns_pipeline_result_when_done(
        self, pipeline, engine, mock_repo, mock_db,
    ):
        """get_current_step returns PipelineResult when pipeline_stage is done."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        row.status = SessionStatus.COMPLETED
        row.pipeline_stage = PipelineStage.DONE.value
        row.result = {
            "departments": ["dept001"],
            "severity": "sev001",
            "diagnoses": [
                {"disease_id": "d001", "confidence": 0.9},
            ],
            "reason": "All done",
        }

        step = await pipeline.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        assert isinstance(step, PipelineResult), "Expected PipelineResult"
        assert step.type == "pipeline_result"
        assert len(step.diagnoses) == 1, "Should have 1 diagnosis"
        assert step.diagnoses[0].disease_id == "d001"
        assert step.departments[0]["id"] == "dept001"


# =====================================================================
# Tests: No generator / no predictor
# =====================================================================


class TestNoGeneratorNoPredictor:
    """Pipeline handles missing generator and/or predictor gracefully."""

    @pytest.mark.asyncio
    async def test_no_generator_skips_llm_questioning(
        self, pipeline_no_generator, engine, mock_repo, mock_db,
    ):
        """Without a generator, pipeline skips straight to prediction."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        row.status = SessionStatus.COMPLETED
        row.current_phase = 5
        row.primary_symptom = "Headache"
        row.demographics = {"gender": "Male", "age": 30}
        row.result = {
            "departments": ["dept001"],
            "severity": "sev001",
            "reason": "test",
        }

        term_step = TerminationStep(
            type="completed", phase=5, departments=[], severity=None, reason="test",
        )

        result = await pipeline_no_generator._handle_rule_based_end(
            mock_db, row, term_step,
        )

        assert isinstance(result, PipelineResult), "Expected PipelineResult"
        assert row.pipeline_stage == PipelineStage.DONE.value
        # Predictor was available, so diagnoses should be populated
        assert len(result.diagnoses) == 2

    @pytest.mark.asyncio
    async def test_no_predictor_returns_empty_diagnoses(
        self, pipeline_no_predictor, engine, mock_repo, mock_db,
    ):
        """Without a predictor, pipeline returns empty diagnoses list."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        row.status = SessionStatus.COMPLETED
        row.current_phase = 5
        row.primary_symptom = "Headache"
        row.demographics = {"gender": "Male", "age": 30}
        row.pipeline_stage = PipelineStage.LLM_QUESTIONING.value
        row.llm_questions = ["Q?"]
        row.result = {
            "departments": ["dept001"],
            "severity": "sev001",
            "reason": "test",
        }

        answers = [LLMAnswer(question="Q?", answer="A")]
        result = await pipeline_no_predictor.submit_llm_answers(
            mock_db, user_id="u1", session_id="s1", answers=answers,
        )

        assert isinstance(result, PipelineResult)
        assert result.diagnoses == [], "No predictor → empty diagnoses"

    @pytest.mark.asyncio
    async def test_bare_pipeline_completes_without_error(
        self, pipeline_bare, engine, mock_repo, mock_db,
    ):
        """Pipeline with no generator and no predictor finishes cleanly."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        row.status = SessionStatus.COMPLETED
        row.current_phase = 5
        row.primary_symptom = "Headache"
        row.demographics = {"gender": "Male", "age": 30}
        row.result = {
            "departments": ["dept001"],
            "severity": "sev001",
            "reason": "test",
        }

        term_step = TerminationStep(
            type="completed", phase=5, departments=[], severity=None, reason="test",
        )

        result = await pipeline_bare._handle_rule_based_end(
            mock_db, row, term_step,
        )

        assert isinstance(result, PipelineResult)
        assert row.pipeline_stage == PipelineStage.DONE.value
        assert result.diagnoses == [], "No predictor → empty diagnoses"


# =====================================================================
# Tests: QAPair building
# =====================================================================


class TestQAPairBuilding:
    """Verify _build_qa_pairs extracts correct data from session state."""

    @pytest.mark.asyncio
    async def test_builds_demographic_pairs(
        self, pipeline, engine, mock_repo, mock_db,
    ):
        """Demographics are extracted as QAPair with phase=0."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.demographics = {"gender": "Male", "age": 30, "date_of_birth": "1994-06-15"}

        pairs = pipeline._build_qa_pairs(row)
        # Find demographic pairs
        demo_pairs = [p for p in pairs if p.phase == 0]
        assert len(demo_pairs) > 0, "Should have demographic pairs"
        assert all(p.source == "rule_based" for p in demo_pairs), (
            "All demographic pairs should be rule_based"
        )

    @pytest.mark.asyncio
    async def test_builds_symptom_pairs(
        self, pipeline, engine, mock_repo, mock_db,
    ):
        """Symptom selection is extracted as QAPair with phase=2."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.primary_symptom = "Headache"
        row.secondary_symptoms = ["Fever"]

        pairs = pipeline._build_qa_pairs(row)
        symptom_pairs = [p for p in pairs if p.phase == 2]
        assert len(symptom_pairs) == 2, (
            "Should have primary + secondary symptom pairs"
        )
        assert symptom_pairs[0].answer == "Headache"
        assert symptom_pairs[1].answer == ["Fever"]

    @pytest.mark.asyncio
    async def test_builds_er_critical_pairs(
        self, pipeline, engine, mock_repo, mock_db,
    ):
        """ER critical responses are extracted as QAPair with phase=1."""
        store = engine._store
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        # Record some ER critical responses
        for item in store.er_critical:
            row.responses[item.qid] = {
                "value": False,
                "answered_at": "2024-01-01T00:00:00",
            }

        pairs = pipeline._build_qa_pairs(row)
        er_pairs = [p for p in pairs if p.phase == 1]
        assert len(er_pairs) == len(store.er_critical), (
            f"Expected {len(store.er_critical)} ER critical pairs, "
            f"got {len(er_pairs)}"
        )

    @pytest.mark.asyncio
    async def test_skips_pending_key(
        self, pipeline, engine, mock_repo, mock_db,
    ):
        """The __pending metadata key is not included in QA pairs."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.responses = {
            "__pending": ["some_qid"],
            "test_qid": {"value": "test", "answered_at": "2024-01-01"},
        }

        pairs = pipeline._build_qa_pairs(row)
        qids = [p.qid for p in pairs]
        assert "__pending" not in qids, "__pending should be excluded"


# =====================================================================
# Tests: QID auto-derivation (qid=None)
# =====================================================================


class TestQidAutoDerivation:
    """Pipeline passes qid=None through to the engine correctly.

    For bulk phases, qid is unused — omitting it should work.
    For sequential phases, the engine auto-derives the qid.
    """

    @pytest.mark.asyncio
    async def test_submit_answer_without_qid_bulk(self, pipeline, mock_db):
        """Pipeline forwards qid=None for bulk phases without error."""
        await pipeline.create_session(mock_db, user_id="u1", session_id="s1")
        # Phase 0: submit demographics without qid
        step = await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value={"gender": "Male", "age": 30},
        )
        assert isinstance(step, QuestionsStep), "Expected QuestionsStep"
        assert step.phase == 1, "Should advance to phase 1"

    @pytest.mark.asyncio
    async def test_submit_answer_without_qid_sequential(
        self, pipeline, engine, mock_db,
    ):
        """Pipeline forwards qid=None for sequential phases; engine auto-derives."""
        store = engine._store

        # Advance through bulk phases to reach sequential
        await pipeline.create_session(mock_db, user_id="u1", session_id="s1")
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics", value={"gender": "Male", "age": 30},
        )
        er_responses = {item.qid: False for item in store.er_critical}
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms", value={"primary_symptom": "Headache"},
        )
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )

        # Now in sequential phase — get the current step
        step = await pipeline.get_current_step(
            mock_db, user_id="u1", session_id="s1",
        )
        if not isinstance(step, QuestionsStep):
            # Tree auto-resolved to completion, nothing to test
            return

        # Submit without qid — pipeline passes None, engine auto-derives
        first_q = step.questions[0]
        if first_q.options:
            answer = first_q.options[0]["id"]
        else:
            answer = "test answer"

        next_step = await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            value=answer,
        )
        # Should get a valid step back (could be QuestionsStep, TerminationStep,
        # or PipelineResult if the engine completed)
        assert next_step is not None, "Expected a non-None step result"


# =====================================================================
# Tests: Multi-step sequential through pipeline (regression)
# =====================================================================


class TestPipelineMultiStepSequential:
    """Full pipeline multi-step sequential test.

    Regression test: verifies that submitting multiple sequential answers
    through the pipeline (qid=None) produces distinct, correctly-ordered
    questions and eventually transitions to LLM questioning or result.
    """

    @staticmethod
    def _pick_answer(q):
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

    @pytest.mark.asyncio
    async def test_full_sequential_flow_completes(
        self, pipeline, engine, mock_db,
    ):
        """Drive the full sequential flow through the pipeline to completion."""
        store = engine._store

        # Advance through bulk phases
        await pipeline.create_session(mock_db, user_id="u1", session_id="s1")
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="demographics",
            value={"gender": "Male", "date_of_birth": "1994-06-15"},
        )
        er_responses = {item.qid: False for item in store.er_critical}
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_critical", value=er_responses,
        )
        await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="symptoms", value={"primary_symptom": "Headache"},
        )
        checklist_items = store.get_er_checklist("Headache", pediatric=False)
        checklist_responses = {item.qid: False for item in checklist_items}
        step = await pipeline.submit_answer(
            mock_db, user_id="u1", session_id="s1",
            qid="er_checklist", value=checklist_responses,
        )

        # Drive through all sequential questions
        seen_qids = []
        seq_count = 0
        while isinstance(step, QuestionsStep):
            q = step.questions[0]
            seen_qids.append(q.qid)
            answer = self._pick_answer(q)
            step = await pipeline.submit_answer(
                mock_db, user_id="u1", session_id="s1",
                value=answer,
            )
            seq_count += 1
            # Safety limit to prevent infinite loops
            assert seq_count < 50, (
                f"Sequential loop exceeded 50 iterations — possible infinite loop"
            )

        # After sequential phase, pipeline should transition to LLM or result
        assert isinstance(step, (LLMQuestionsStep, PipelineResult)), (
            f"Expected LLMQuestionsStep or PipelineResult after sequential, "
            f"got {type(step).__name__}"
        )

        # Verify all qids were unique (no question presented twice)
        assert len(seen_qids) == len(set(seen_qids)), (
            f"Duplicate qid in sequential flow: {seen_qids}"
        )

        # Should have answered at least 3 sequential questions for Headache
        assert seq_count >= 3, (
            f"Expected at least 3 sequential questions for Headache, got {seq_count}"
        )
