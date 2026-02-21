"""PromptManager tests — verify LLM prompt rendering for all step types.

Tests construct QuestionsStep objects directly (no DB needed) and call
PromptManager.render_step() to verify prompt output contains the expected
elements: field names, option IDs, JSON format instructions, etc.

Also includes an end-to-end test using the pipeline's get_llm_prompt method
with mocked DB infrastructure.
"""

from unittest.mock import AsyncMock

import pytest

from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.models.session import QuestionPayload, QuestionsStep
from prescreen_rulesets.pipeline import PrescreenPipeline
from prescreen_rulesets.prompt import PromptManager
from prescreen_rulesets.ruleset import RulesetStore

# Import mock infrastructure from test_engine
from test_engine import MockRepository


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
def pm():
    """Fresh PromptManager for each test."""
    return PromptManager()


# =====================================================================
# Bulk phase prompt tests
# =====================================================================


class TestRenderDemographicsPrompt:
    """Phase 0 (Demographics) prompt rendering."""

    def test_render_demographics_prompt(self, pm):
        """Demographics prompt includes field names and JSON instruction."""
        step = QuestionsStep(
            phase=0,
            phase_name="Demographics",
            questions=[
                QuestionPayload(
                    qid="demo_dob",
                    question="วันเกิด",
                    question_type="datetime",
                    answer_schema={"type": "string", "format": "date"},
                    metadata={"key": "date_of_birth", "field_name": "Date of Birth", "optional": False},
                ),
                QuestionPayload(
                    qid="demo_gender",
                    question="เพศ",
                    question_type="enum",
                    answer_schema={"type": "string", "enum": ["Male", "Female"]},
                    options=[{"id": "Male", "label": "Male"}, {"id": "Female", "label": "Female"}],
                    metadata={"key": "gender", "field_name": "Gender", "optional": False},
                ),
                QuestionPayload(
                    qid="demo_height",
                    question="ส่วนสูง",
                    question_type="float",
                    answer_schema={"type": "number"},
                    metadata={"key": "height", "field_name": "Height", "optional": True},
                ),
            ],
            submission_schema={
                "type": "object",
                "properties": {
                    "date_of_birth": {"type": "string", "format": "date"},
                    "gender": {"type": "string", "enum": ["Male", "Female"]},
                    "height": {"type": "number"},
                },
                "required": ["date_of_birth", "gender"],
            },
        )
        prompt = pm.render_step(step)

        assert "demographic" in prompt.lower(), "Prompt should mention demographics"
        assert "date_of_birth" in prompt, "Prompt should include field key 'date_of_birth'"
        assert "gender" in prompt, "Prompt should include field key 'gender'"
        assert "JSON" in prompt, "Prompt should include JSON format instruction"
        assert "date" in prompt, "Prompt should mention date format"
        assert "[optional]" in prompt, "Prompt should mark optional fields"


class TestRenderERCriticalPrompt:
    """Phase 1 (ER Critical Screen) prompt rendering."""

    def test_render_er_critical_prompt(self, pm):
        """ER critical prompt includes qids and boolean format instruction."""
        step = QuestionsStep(
            phase=1,
            phase_name="ER Critical Screen",
            questions=[
                QuestionPayload(
                    qid="emer_critical_001",
                    question="หมดสติ / ไม่รู้สึกตัว",
                    question_type="yes_no",
                    answer_schema={"type": "boolean"},
                ),
                QuestionPayload(
                    qid="emer_critical_002",
                    question="หายใจลำบาก",
                    question_type="yes_no",
                    answer_schema={"type": "boolean"},
                ),
            ],
            submission_schema={
                "type": "object",
                "properties": {
                    "emer_critical_001": {"type": "boolean"},
                    "emer_critical_002": {"type": "boolean"},
                },
                "required": ["emer_critical_001", "emer_critical_002"],
            },
        )
        prompt = pm.render_step(step)

        assert "critical" in prompt.lower(), "Prompt should mention critical conditions"
        assert "emer_critical_001" in prompt, "Prompt should include qid"
        assert "emer_critical_002" in prompt, "Prompt should include qid"
        assert "true/false" in prompt or "boolean" in prompt, (
            "Prompt should mention boolean format"
        )


class TestRenderSymptomSelectionPrompt:
    """Phase 2 (Symptom Selection) prompt rendering."""

    def test_render_symptom_selection_prompt(self, pm):
        """Symptom selection prompt lists symptom options and JSON format."""
        step = QuestionsStep(
            phase=2,
            phase_name="Symptom Selection",
            questions=[
                QuestionPayload(
                    qid="primary_symptom",
                    question="อาการหลัก",
                    question_type="single_select",
                    options=[
                        {"id": "Headache", "label": "ปวดศีรษะ"},
                        {"id": "Fever", "label": "ไข้"},
                    ],
                    answer_schema={"type": "string", "enum": ["Headache", "Fever"]},
                ),
                QuestionPayload(
                    qid="secondary_symptoms",
                    question="อาการร่วม (ถ้ามี)",
                    question_type="multi_select",
                    options=[
                        {"id": "Headache", "label": "ปวดศีรษะ"},
                        {"id": "Fever", "label": "ไข้"},
                    ],
                    answer_schema={
                        "type": "array",
                        "items": {"type": "string", "enum": ["Headache", "Fever"]},
                    },
                    metadata={"optional": True},
                ),
            ],
            submission_schema={
                "type": "object",
                "properties": {
                    "primary_symptom": {"type": "string", "enum": ["Headache", "Fever"]},
                    "secondary_symptoms": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["Headache", "Fever"]},
                    },
                },
                "required": ["primary_symptom"],
            },
        )
        prompt = pm.render_step(step)

        assert "symptom" in prompt.lower(), "Prompt should mention symptom selection"
        assert "Headache" in prompt, "Prompt should list Headache option"
        assert "Fever" in prompt, "Prompt should list Fever option"
        assert "primary_symptom" in prompt, "Prompt should mention primary_symptom"
        assert "JSON" in prompt, "Prompt should include JSON format instruction"


class TestRenderERChecklistPrompt:
    """Phase 3 (ER Checklist) prompt rendering."""

    def test_render_er_checklist_prompt(self, pm):
        """ER checklist prompt includes checklist items and boolean format."""
        step = QuestionsStep(
            phase=3,
            phase_name="ER Checklist",
            questions=[
                QuestionPayload(
                    qid="emer_adult_hea1",
                    question="ปวดหัวอย่างรุนแรง",
                    question_type="yes_no",
                    answer_schema={"type": "boolean"},
                    metadata={"symptom": "Headache"},
                ),
                QuestionPayload(
                    qid="emer_adult_hea2",
                    question="มีไข้สูง",
                    question_type="yes_no",
                    answer_schema={"type": "boolean"},
                    metadata={"symptom": "Headache"},
                ),
            ],
            submission_schema={
                "type": "object",
                "properties": {
                    "emer_adult_hea1": {"type": "boolean"},
                    "emer_adult_hea2": {"type": "boolean"},
                },
                "required": ["emer_adult_hea1", "emer_adult_hea2"],
            },
        )
        prompt = pm.render_step(step)

        assert "checklist" in prompt.lower(), "Prompt should mention checklist"
        assert "emer_adult_hea1" in prompt, "Prompt should include checklist qid"
        assert "emer_adult_hea2" in prompt, "Prompt should include checklist qid"
        assert "true/false" in prompt or "boolean" in prompt, (
            "Prompt should mention boolean format"
        )


# =====================================================================
# Sequential phase prompt tests
# =====================================================================


class TestRenderSingleSelectPrompt:
    """Single-select sequential prompt rendering."""

    def test_render_single_select_prompt(self, pm):
        """Single-select prompt lists option IDs and string format instruction."""
        step = QuestionsStep(
            phase=4,
            phase_name="OLDCARTS",
            questions=[
                QuestionPayload(
                    qid="hea_o_001",
                    question="อาการเริ่มต้นเป็นอย่างไร?",
                    question_type="single_select",
                    options=[
                        {"id": "sudden", "label": "เฉียบพลัน"},
                        {"id": "gradual", "label": "ค่อยเป็นค่อยไป"},
                    ],
                    answer_schema={"type": "string", "enum": ["sudden", "gradual"]},
                ),
            ],
            submission_schema={"type": "string", "enum": ["sudden", "gradual"]},
        )
        prompt = pm.render_step(step)

        assert "อาการเริ่มต้นเป็นอย่างไร" in prompt, "Prompt should include question text"
        assert "sudden" in prompt, "Prompt should list option ID 'sudden'"
        assert "gradual" in prompt, "Prompt should list option ID 'gradual'"
        assert "Question" in prompt, "Prompt should present the question label"


class TestRenderMultiSelectPrompt:
    """Multi-select sequential prompt rendering."""

    def test_render_multi_select_prompt(self, pm):
        """Multi-select prompt includes array format instruction."""
        step = QuestionsStep(
            phase=4,
            phase_name="OLDCARTS",
            questions=[
                QuestionPayload(
                    qid="hea_c_001",
                    question="ลักษณะอาการปวด",
                    question_type="multi_select",
                    options=[
                        {"id": "throbbing", "label": "ปวดตุ๊บๆ"},
                        {"id": "pressure", "label": "ปวดแน่นๆ"},
                    ],
                    answer_schema={
                        "type": "array",
                        "items": {"type": "string", "enum": ["throbbing", "pressure"]},
                    },
                ),
            ],
            submission_schema={
                "type": "array",
                "items": {"type": "string", "enum": ["throbbing", "pressure"]},
            },
        )
        prompt = pm.render_step(step)

        assert "ลักษณะอาการปวด" in prompt, "Prompt should include question text"
        assert "throbbing" in prompt, "Prompt should list option ID"
        assert "array" in prompt.lower() or "[" in prompt, (
            "Prompt should indicate array format"
        )


class TestRenderNumberRangePrompt:
    """Number range sequential prompt rendering."""

    def test_render_number_range_prompt(self, pm):
        """Number range prompt includes min/max and number format instruction."""
        step = QuestionsStep(
            phase=4,
            phase_name="OLDCARTS",
            questions=[
                QuestionPayload(
                    qid="hea_s_001",
                    question="ระดับความปวด (0-10)",
                    question_type="number_range",
                    constraints={"min": 0, "max": 10, "step": 1, "default": 5},
                    answer_schema={"type": "number", "minimum": 0, "maximum": 10},
                ),
            ],
            submission_schema={"type": "number", "minimum": 0, "maximum": 10},
        )
        prompt = pm.render_step(step)

        assert "ระดับความปวด" in prompt, "Prompt should include question text"
        assert "0" in prompt and "10" in prompt, "Prompt should include min/max range"
        assert "number" in prompt.lower() or "JSON" in prompt, (
            "Prompt should mention number format"
        )


class TestRenderFreeTextPrompt:
    """Free text sequential prompt rendering."""

    def test_render_free_text_prompt(self, pm):
        """Free text prompt includes string format instruction."""
        step = QuestionsStep(
            phase=5,
            phase_name="OPD",
            questions=[
                QuestionPayload(
                    qid="hea_opd_001",
                    question="อธิบายอาการเพิ่มเติม",
                    question_type="free_text",
                    answer_schema={"type": "string"},
                ),
            ],
            submission_schema={"type": "string"},
        )
        prompt = pm.render_step(step)

        assert "อธิบายอาการเพิ่มเติม" in prompt, "Prompt should include question text"
        assert "string" in prompt.lower() or "JSON" in prompt, (
            "Prompt should mention string format"
        )


# =====================================================================
# Integration test: pipeline get_llm_prompt
# =====================================================================


class TestRenderLLMQuestionsPrompt:
    """LLM-generated follow-up questions prompt rendering."""

    def test_render_llm_questions_prompt(self, pm):
        """LLM questions prompt lists questions and JSON array instruction."""
        questions = [
            "อาการปวดรุนแรงแค่ไหน?",
            "มีอาการคลื่นไส้ร่วมด้วยไหม?",
        ]
        prompt = pm.render_llm_questions(questions)

        assert "อาการปวดรุนแรงแค่ไหน?" in prompt, (
            "Prompt should include first LLM question"
        )
        assert "มีอาการคลื่นไส้ร่วมด้วยไหม?" in prompt, (
            "Prompt should include second LLM question"
        )
        assert "JSON" in prompt, "Prompt should include JSON format instruction"
        assert "answer" in prompt, "Prompt should mention 'answer' in response format"

    def test_render_single_llm_question(self, pm):
        """LLM questions prompt works with a single question."""
        prompt = pm.render_llm_questions(["คุณมีไข้ไหม?"])
        assert "คุณมีไข้ไหม?" in prompt, "Prompt should include the question"
        assert "JSON" in prompt, "Prompt should include JSON format instruction"


# =====================================================================
# Integration test: pipeline get_llm_prompt
# =====================================================================


class TestPipelineGetLLMPrompt:
    """End-to-end test: pipeline.get_llm_prompt returns a non-empty prompt."""

    @pytest.mark.asyncio
    async def test_pipeline_get_llm_prompt(self, store):
        """Create a session and call get_llm_prompt — verify non-empty string."""
        mock_repo = MockRepository()
        mock_db = AsyncMock()

        engine = PrescreenEngine(store)
        engine._repo = mock_repo

        pipeline = PrescreenPipeline(engine, store)
        pipeline._repo = mock_repo

        # Create session
        await engine.create_session(mock_db, user_id="u1", session_id="s1")

        # Phase 0 should produce a demographics prompt
        prompt = await pipeline.get_llm_prompt(
            mock_db, user_id="u1", session_id="s1",
        )
        assert prompt is not None, "Prompt should not be None for phase 0"
        assert len(prompt) > 0, "Prompt should be non-empty"
        assert "demographic" in prompt.lower(), "Prompt should mention demographics"

    @pytest.mark.asyncio
    async def test_pipeline_get_llm_prompt_returns_none_when_done(self, store):
        """get_llm_prompt returns None when the session is terminated."""
        from prescreen_db.models.enums import SessionStatus

        mock_repo = MockRepository()
        mock_db = AsyncMock()

        engine = PrescreenEngine(store)
        engine._repo = mock_repo

        pipeline = PrescreenPipeline(engine, store)
        pipeline._repo = mock_repo

        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.TERMINATED

        prompt = await pipeline.get_llm_prompt(
            mock_db, user_id="u1", session_id="s1",
        )
        assert prompt is None, "Prompt should be None for terminated session"

    @pytest.mark.asyncio
    async def test_pipeline_get_llm_prompt_during_llm_questioning(self, store):
        """get_llm_prompt renders LLM follow-up questions during llm_questioning stage."""
        from prescreen_db.models.enums import PipelineStage, SessionStatus

        mock_repo = MockRepository()
        mock_db = AsyncMock()

        engine = PrescreenEngine(store)
        engine._repo = mock_repo

        pipeline = PrescreenPipeline(engine, store)
        pipeline._repo = mock_repo

        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        # Simulate entering llm_questioning stage
        row.status = SessionStatus.COMPLETED
        row.pipeline_stage = PipelineStage.LLM_QUESTIONING.value
        row.llm_questions = [
            "อาการปวดรุนแรงแค่ไหน?",
            "มีอาการคลื่นไส้ร่วมด้วยไหม?",
        ]

        prompt = await pipeline.get_llm_prompt(
            mock_db, user_id="u1", session_id="s1",
        )
        assert prompt is not None, "Prompt should not be None for llm_questioning"
        assert "อาการปวดรุนแรงแค่ไหน?" in prompt, (
            "Prompt should include LLM question text"
        )
        assert "JSON" in prompt, "Prompt should include JSON format instruction"

    @pytest.mark.asyncio
    async def test_pipeline_get_llm_prompt_returns_none_when_pipeline_done(self, store):
        """get_llm_prompt returns None when pipeline_stage is done."""
        from prescreen_db.models.enums import PipelineStage, SessionStatus

        mock_repo = MockRepository()
        mock_db = AsyncMock()

        engine = PrescreenEngine(store)
        engine._repo = mock_repo

        pipeline = PrescreenPipeline(engine, store)
        pipeline._repo = mock_repo

        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        row.status = SessionStatus.COMPLETED
        row.pipeline_stage = PipelineStage.DONE.value

        prompt = await pipeline.get_llm_prompt(
            mock_db, user_id="u1", session_id="s1",
        )
        assert prompt is None, "Prompt should be None when pipeline is done"


# =====================================================================
# History in prompts
# =====================================================================


class TestRenderStepWithHistory:
    """Verify that passing history to render methods includes Q&A context."""

    def test_render_step_with_history(self, pm):
        """Sequential prompt includes previous answers when history is given."""
        from prescreen_rulesets.models.pipeline import QAPair

        history = [
            QAPair(question="เพศ", answer="Male", source="rule_based", phase=0),
            QAPair(question="อายุ", answer=30, source="rule_based", phase=0),
        ]
        step = QuestionsStep(
            phase=4,
            phase_name="OLDCARTS",
            questions=[
                QuestionPayload(
                    qid="hea_o_001",
                    question="อาการเริ่มต้นเป็นอย่างไร?",
                    question_type="single_select",
                    options=[
                        {"id": "sudden", "label": "เฉียบพลัน"},
                        {"id": "gradual", "label": "ค่อยเป็นค่อยไป"},
                    ],
                    answer_schema={"type": "string", "enum": ["sudden", "gradual"]},
                ),
            ],
            submission_schema={"type": "string", "enum": ["sudden", "gradual"]},
        )
        prompt = pm.render_step(step, history=history)

        assert "Previous answers" in prompt, (
            "Prompt should include 'Previous answers' header when history is given"
        )
        assert "เพศ" in prompt, "Prompt should include history question text"
        assert "Male" in prompt, "Prompt should include history answer"
        assert "อายุ" in prompt, "Prompt should include second history question"

    def test_render_step_without_history(self, pm):
        """Sequential prompt omits history section when history is None."""
        step = QuestionsStep(
            phase=4,
            phase_name="OLDCARTS",
            questions=[
                QuestionPayload(
                    qid="hea_o_001",
                    question="อาการเริ่มต้นเป็นอย่างไร?",
                    question_type="single_select",
                    options=[
                        {"id": "sudden", "label": "เฉียบพลัน"},
                        {"id": "gradual", "label": "ค่อยเป็นค่อยไป"},
                    ],
                    answer_schema={"type": "string", "enum": ["sudden", "gradual"]},
                ),
            ],
            submission_schema={"type": "string", "enum": ["sudden", "gradual"]},
        )
        prompt = pm.render_step(step, history=None)

        assert "Previous answers" not in prompt, (
            "Prompt should NOT include history section when history is None"
        )

    def test_render_step_with_empty_history(self, pm):
        """Sequential prompt omits history section when history is empty list."""
        step = QuestionsStep(
            phase=4,
            phase_name="OLDCARTS",
            questions=[
                QuestionPayload(
                    qid="hea_o_001",
                    question="อาการเริ่มต้นเป็นอย่างไร?",
                    question_type="single_select",
                    options=[
                        {"id": "sudden", "label": "เฉียบพลัน"},
                        {"id": "gradual", "label": "ค่อยเป็นค่อยไป"},
                    ],
                    answer_schema={"type": "string", "enum": ["sudden", "gradual"]},
                ),
            ],
            submission_schema={"type": "string", "enum": ["sudden", "gradual"]},
        )
        prompt = pm.render_step(step, history=[])

        assert "Previous answers" not in prompt, (
            "Prompt should NOT include history section when history is empty"
        )


class TestRenderLLMQuestionsWithHistory:
    """Verify LLM questions prompt includes history when provided."""

    def test_render_llm_questions_with_history(self, pm):
        """LLM questions prompt prepends Q&A history."""
        from prescreen_rulesets.models.pipeline import QAPair

        history = [
            QAPair(question="อาการหลัก", answer="Headache", source="rule_based", phase=2),
        ]
        questions = ["อาการปวดรุนแรงแค่ไหน?"]
        prompt = pm.render_llm_questions(questions, history=history)

        assert "Previous answers" in prompt, (
            "LLM prompt should include history section"
        )
        assert "อาการหลัก" in prompt, "LLM prompt should include history question"
        assert "Headache" in prompt, "LLM prompt should include history answer"
        assert "อาการปวดรุนแรงแค่ไหน?" in prompt, (
            "LLM prompt should still include the LLM question"
        )

    def test_render_llm_questions_without_history(self, pm):
        """LLM questions prompt omits history when not provided."""
        questions = ["อาการปวดรุนแรงแค่ไหน?"]
        prompt = pm.render_llm_questions(questions)

        assert "Previous answers" not in prompt, (
            "LLM prompt should NOT include history when not provided"
        )


class TestPipelineGetLLMPromptWithHistory:
    """Integration: pipeline.get_llm_prompt include_history parameter."""

    @pytest.mark.asyncio
    async def test_include_history_true_includes_qa_pairs(self, store):
        """With include_history=True and existing answers, prompt has history."""
        mock_repo = MockRepository()
        mock_db = AsyncMock()

        engine = PrescreenEngine(store)
        engine._repo = mock_repo

        pipeline = PrescreenPipeline(engine, store)
        pipeline._repo = mock_repo

        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        # Simulate demographics already answered — move session to phase 1
        row.demographics = {"gender": "Male", "date_of_birth": "1990-01-01"}
        row.current_phase = 1

        prompt = await pipeline.get_llm_prompt(
            mock_db, user_id="u1", session_id="s1",
            include_history=True,
        )
        assert prompt is not None, "Prompt should not be None"
        # Demographics answers should appear in history
        assert "Previous answers" in prompt, (
            "Prompt should include history section with demographics answers"
        )
        assert "Male" in prompt, "History should include gender answer"

    @pytest.mark.asyncio
    async def test_include_history_false_omits_qa_pairs(self, store):
        """With include_history=False, prompt has no history section."""
        mock_repo = MockRepository()
        mock_db = AsyncMock()

        engine = PrescreenEngine(store)
        engine._repo = mock_repo

        pipeline = PrescreenPipeline(engine, store)
        pipeline._repo = mock_repo

        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]

        row.demographics = {"gender": "Male", "date_of_birth": "1990-01-01"}
        row.current_phase = 1

        prompt = await pipeline.get_llm_prompt(
            mock_db, user_id="u1", session_id="s1",
            include_history=False,
        )
        assert prompt is not None, "Prompt should not be None"
        assert "Previous answers" not in prompt, (
            "Prompt should NOT include history section when include_history=False"
        )
