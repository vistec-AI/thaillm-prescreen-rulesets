"""Tests for OpenAIPredictionModule and its prompt manager.

Covers:
  - _filter_qa_pairs: phase 3 negative removal, other phases unchanged
  - _build_response_format: validates JSON schema has correct enums
  - _parse_response: JSON parsing, max diagnoses cap
  - _apply_safety_constraints: ER override, min severity enforcement
  - Full predict() flow with mocked OpenAI client
  - Re-prompt on fewer than 3 diagnoses
  - Transient error handling (graceful degradation)
  - Permanent error handling (re-raised)
  - Prompt rendering: system prompt is lean, user prompt contains reference tables
  - set_context: context stored and used correctly
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from prescreen_rulesets.models.pipeline import (
    DiagnosisResult,
    PredictionResult,
    QAPair,
)
from prescreen_rulesets.prediction.openai import OpenAIPredictionModule
from prescreen_rulesets.prediction.prompt_manager import PredictionPromptManager
from prescreen_rulesets.ruleset import RulesetStore


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(scope="module")
def store() -> RulesetStore:
    """Load a real RulesetStore for testing."""
    s = RulesetStore()
    s.load()
    return s


@pytest.fixture
def predictor(store: RulesetStore) -> OpenAIPredictionModule:
    """Create a predictor with a test API key."""
    return OpenAIPredictionModule(api_key="test-key", store=store)


# =====================================================================
# Sample QA pairs for testing
# =====================================================================

def _make_qa_pairs() -> list[QAPair]:
    """Build a representative set of QA pairs across phases."""
    return [
        QAPair(
            question="อายุ", answer=35, source="rule_based",
            qid="demo_age", question_type="number_range", phase=0,
        ),
        QAPair(
            question="เพศ", answer="ชาย", source="rule_based",
            qid="demo_gender", question_type="single_select", phase=0,
        ),
        QAPair(
            question="หายใจลำบาก?", answer=False, source="rule_based",
            qid="emer_critical_1", question_type="single_select", phase=1,
        ),
        QAPair(
            question="อาการปวดท้องรุนแรง?", answer=True, source="rule_based",
            qid="emer_adult_abd1", question_type="single_select", phase=3,
        ),
        QAPair(
            question="มีไข้สูง?", answer=False, source="rule_based",
            qid="emer_adult_abd2", question_type="single_select", phase=3,
        ),
        QAPair(
            question="ปวดบริเวณไหน?", answer="ท้องน้อยด้านขวา", source="rule_based",
            qid="abd_o_1", question_type="free_text", phase=4,
        ),
        QAPair(
            question="มียาที่ทานอยู่ไหม?", answer="ไม่มี", source="llm_generated",
        ),
    ]


# =====================================================================
# LLM provider resolution tests
# =====================================================================

class TestLLMConfigResolution:
    """Tests for OPENAI_API_KEY / OPENROUTER_API_KEY fallback in __init__."""

    def test_openai_key_takes_priority(self, monkeypatch, store):
        """When both keys are set, OPENAI_API_KEY wins."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter")
        pred = OpenAIPredictionModule(store=store)
        assert pred._model == "gpt-5.4", (
            "OpenAI provider should keep the default model name"
        )

    def test_openrouter_fallback_sets_model(self, monkeypatch, store):
        """When only OPENROUTER_API_KEY is set, model becomes openai/gpt-5.4."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter")
        pred = OpenAIPredictionModule(store=store)
        assert pred._model == "openai/gpt-5.4", (
            "OpenRouter fallback should prefix the model name"
        )

    def test_explicit_api_key_skips_resolution(self, monkeypatch, store):
        """When api_key is explicitly provided, env fallback is skipped."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        pred = OpenAIPredictionModule(api_key="explicit-key", store=store)
        assert pred._model == "gpt-5.4", (
            "Explicit api_key should skip env-var resolution"
        )


# =====================================================================
# _filter_qa_pairs tests
# =====================================================================

class TestFilterQAPairs:
    """Tests for phase 3 negative-answer filtering."""

    def test_removes_phase3_false_answers(self, predictor):
        """Phase 3 entries with answer=False are excluded."""
        pairs = _make_qa_pairs()
        filtered = predictor._filter_qa_pairs(pairs)

        phase3_qids = [p.qid for p in filtered if p.phase == 3]
        assert "emer_adult_abd2" not in phase3_qids, (
            "Phase 3 negative answer should be filtered out"
        )
        assert "emer_adult_abd1" in phase3_qids, (
            "Phase 3 positive answer should be kept"
        )

    def test_keeps_all_other_phases(self, predictor):
        """Non-phase-3 entries pass through regardless of answer value."""
        pairs = _make_qa_pairs()
        filtered = predictor._filter_qa_pairs(pairs)

        phase1_qids = [p.qid for p in filtered if p.phase == 1]
        assert "emer_critical_1" in phase1_qids, (
            "Phase 1 False answer should NOT be filtered"
        )

    def test_keeps_llm_generated_pairs(self, predictor):
        """LLM-generated pairs (no phase) pass through."""
        pairs = _make_qa_pairs()
        filtered = predictor._filter_qa_pairs(pairs)
        llm_pairs = [p for p in filtered if p.source == "llm_generated"]
        assert len(llm_pairs) == 1, "LLM-generated pair should be kept"

    def test_empty_input(self, predictor):
        """Empty input returns empty output."""
        assert predictor._filter_qa_pairs([]) == []


# =====================================================================
# _build_response_format tests
# =====================================================================

class TestResponseFormatSchema:
    """Validates the structured output JSON schema."""

    def test_schema_has_all_disease_ids(self, predictor, store):
        """Disease ID enum contains all diseases from the store."""
        schema = predictor._response_format
        disease_enum = (
            schema["json_schema"]["schema"]["properties"]["diagnoses"]
            ["items"]["properties"]["disease_id"]["enum"]
        )
        expected_ids = store.get_disease_ids()
        assert disease_enum == expected_ids, (
            f"Expected {len(expected_ids)} disease IDs, got {len(disease_enum)}"
        )

    def test_schema_has_all_department_ids(self, predictor, store):
        """Department ID enum contains all departments from the store."""
        schema = predictor._response_format
        dept_enum = (
            schema["json_schema"]["schema"]["properties"]["departments"]
            ["items"]["enum"]
        )
        expected_ids = store.get_department_ids()
        assert dept_enum == expected_ids, (
            f"Expected {len(expected_ids)} department IDs, got {len(dept_enum)}"
        )

    def test_schema_has_all_severity_ids(self, predictor, store):
        """Severity ID enum contains all severity levels from the store."""
        schema = predictor._response_format
        sev_enum = (
            schema["json_schema"]["schema"]["properties"]["severity"]["enum"]
        )
        expected_ids = store.get_severity_ids()
        assert sev_enum == expected_ids, (
            f"Expected {len(expected_ids)} severity IDs, got {len(sev_enum)}"
        )

    def test_schema_requires_reasoning(self, predictor):
        """Schema requires a reasoning field for chain-of-thought."""
        schema = predictor._response_format
        required = schema["json_schema"]["schema"]["required"]
        assert "reasoning" in required, "reasoning should be required"

    def test_schema_is_strict(self, predictor):
        """Schema is set to strict mode for guaranteed conformance."""
        schema = predictor._response_format
        assert schema["json_schema"]["strict"] is True


# =====================================================================
# _parse_response tests
# =====================================================================

class TestParseResponse:
    """Tests for _parse_response — raw JSON parsing without safety constraints."""

    def test_valid_response(self, predictor):
        """Standard valid response is parsed correctly."""
        content = json.dumps({
            "diagnoses": [
                {"disease_id": "d001"},
                {"disease_id": "d002"},
                {"disease_id": "d003"},
            ],
            "departments": ["dept004"],
            "severity": "sev002",
            "reasoning": "Likely abdominal injury based on symptoms.",
        })
        result = predictor._parse_response(content)
        assert isinstance(result, PredictionResult)
        assert len(result.diagnoses) == 3
        assert result.diagnoses[0].disease_id == "d001"
        assert result.departments == ["dept004"]
        assert result.severity == "sev002"

    def test_max_diagnoses_cap(self, predictor):
        """Result is truncated at max_diagnoses (10)."""
        diagnoses = [
            {"disease_id": f"d{i:03d}"}
            for i in range(1, 21)
        ]
        content = json.dumps({
            "diagnoses": diagnoses,
            "departments": ["dept001"],
            "severity": "sev001",
            "reasoning": "Many possibilities.",
        })
        result = predictor._parse_response(content)
        assert len(result.diagnoses) == 10, (
            f"Expected 10 diagnoses (max), got {len(result.diagnoses)}"
        )

    def test_fewer_than_3_diagnoses_still_parsed(self, predictor):
        """_parse_response returns the result as-is; min-3 enforcement is in predict()."""
        content = json.dumps({
            "diagnoses": [{"disease_id": "d001"}],
            "departments": ["dept004"],
            "severity": "sev002",
            "reasoning": "Only one diagnosis.",
        })
        result = predictor._parse_response(content)
        assert len(result.diagnoses) == 1, (
            "_parse_response should not enforce min diagnoses"
        )

    def test_invalid_json_returns_empty(self, predictor):
        """Malformed JSON returns empty PredictionResult."""
        result = predictor._parse_response("not json at all")
        assert result.diagnoses == []
        assert result.departments == []
        assert result.severity is None


# =====================================================================
# _apply_safety_constraints tests
# =====================================================================

class TestApplySafetyConstraints:
    """Tests for _apply_safety_constraints — ER override and min severity."""

    def test_er_override(self, predictor):
        """When er_override is set, ER severity and department are forced."""
        parsed = PredictionResult(
            diagnoses=[
                DiagnosisResult(disease_id="d001"),
                DiagnosisResult(disease_id="d002"),
                DiagnosisResult(disease_id="d003"),
            ],
            departments=["dept004"],
            severity="sev001",
        )
        result = predictor._apply_safety_constraints(
            parsed, er_override=True, min_severity=None,
        )
        assert result.severity == "sev003", (
            "ER override should force severity to sev003"
        )
        assert "dept002" in result.departments, (
            "ER override should include dept002"
        )

    def test_min_severity_enforcement(self, predictor):
        """When min_severity is set, predicted severity is bumped up if needed."""
        parsed = PredictionResult(
            diagnoses=[
                DiagnosisResult(disease_id="d001"),
                DiagnosisResult(disease_id="d002"),
                DiagnosisResult(disease_id="d003"),
            ],
            departments=["dept004"],
            severity="sev002",
        )
        result = predictor._apply_safety_constraints(
            parsed, er_override=False, min_severity="sev002_5",
        )
        assert result.severity == "sev002_5", (
            "Severity should be bumped to min_severity sev002_5"
        )

    def test_min_severity_no_bump_when_higher(self, predictor):
        """When predicted severity is already higher, no bump needed."""
        parsed = PredictionResult(
            diagnoses=[
                DiagnosisResult(disease_id="d001"),
                DiagnosisResult(disease_id="d002"),
                DiagnosisResult(disease_id="d003"),
            ],
            departments=["dept004"],
            severity="sev002",
        )
        result = predictor._apply_safety_constraints(
            parsed, er_override=False, min_severity="sev001",
        )
        assert result.severity == "sev002", (
            "Severity should stay at sev002 (higher than min sev001)"
        )

    def test_no_constraints(self, predictor):
        """When no constraints set, result passes through unchanged."""
        parsed = PredictionResult(
            diagnoses=[DiagnosisResult(disease_id="d001")],
            departments=["dept004"],
            severity="sev001",
        )
        result = predictor._apply_safety_constraints(
            parsed, er_override=False, min_severity=None,
        )
        assert result.severity == "sev001"
        assert result.departments == ["dept004"]


# =====================================================================
# set_context tests
# =====================================================================

class TestSetContext:
    """Tests for context setting."""

    def test_set_context_stores_values(self, predictor):
        """set_context stores min_severity and er_override."""
        predictor.set_context(min_severity="sev002", er_override=True)
        assert predictor._min_severity == "sev002"
        assert predictor._er_override is True

    def test_set_context_defaults(self, predictor):
        """set_context defaults to None/False when not specified."""
        predictor.set_context()
        assert predictor._min_severity is None
        assert predictor._er_override is False


# =====================================================================
# Full predict() flow with mocked OpenAI client
# =====================================================================

class TestPredictFlow:
    """Integration tests for predict() with mocked AsyncOpenAI."""

    def _mock_response(self, content: str) -> MagicMock:
        """Build a mock OpenAI response with the given content."""
        mock_message = MagicMock()
        mock_message.content = content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    @pytest.mark.asyncio
    async def test_predict_success(self, predictor):
        """Successful API call returns parsed PredictionResult."""
        content = json.dumps({
            "diagnoses": [
                {"disease_id": "d001"},
                {"disease_id": "d003"},
                {"disease_id": "d005"},
            ],
            "departments": ["dept004"],
            "severity": "sev002",
            "reasoning": "Based on symptoms, abdominal injury most likely.",
        })
        predictor._client.chat.completions.create = AsyncMock(
            return_value=self._mock_response(content),
        )

        result = await predictor.predict(_make_qa_pairs())

        assert isinstance(result, PredictionResult)
        assert len(result.diagnoses) == 3
        assert result.diagnoses[0].disease_id == "d001"
        assert result.departments == ["dept004"]
        assert result.severity == "sev002"

    @pytest.mark.asyncio
    async def test_predict_uses_structured_output(self, predictor):
        """predict() passes response_format with json_schema to the API."""
        content = json.dumps({
            "diagnoses": [
                {"disease_id": "d001"},
                {"disease_id": "d002"},
                {"disease_id": "d003"},
            ],
            "departments": ["dept001"],
            "severity": "sev001",
            "reasoning": "Test.",
        })
        predictor._client.chat.completions.create = AsyncMock(
            return_value=self._mock_response(content),
        )

        await predictor.predict([])

        call_args = predictor._client.chat.completions.create.call_args
        response_format = call_args.kwargs["response_format"]
        assert response_format["type"] == "json_schema", (
            "Should use json_schema response format"
        )

    @pytest.mark.asyncio
    async def test_predict_transient_error_returns_empty(self, predictor):
        """Transient API errors return empty PredictionResult."""
        import openai as openai_mod

        predictor._client.chat.completions.create = AsyncMock(
            side_effect=openai_mod.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body=None,
            ),
        )

        result = await predictor.predict(_make_qa_pairs())
        assert result.diagnoses == [], (
            "Transient error should return empty diagnoses"
        )
        assert result.departments == []
        assert result.severity is None

    @pytest.mark.asyncio
    async def test_predict_auth_error_reraises(self, predictor):
        """Permanent errors (auth) are re-raised to the caller."""
        import openai as openai_mod

        predictor._client.chat.completions.create = AsyncMock(
            side_effect=openai_mod.AuthenticationError(
                message="invalid api key",
                response=MagicMock(status_code=401, headers={}),
                body=None,
            ),
        )

        with pytest.raises(openai_mod.AuthenticationError):
            await predictor.predict(_make_qa_pairs())

    @pytest.mark.asyncio
    async def test_predict_with_context(self, predictor):
        """predict() with set_context applies ER override correctly."""
        predictor.set_context(er_override=True, min_severity="sev002")

        content = json.dumps({
            "diagnoses": [
                {"disease_id": "d001"},
                {"disease_id": "d002"},
                {"disease_id": "d003"},
            ],
            "departments": ["dept004"],
            "severity": "sev001",
            "reasoning": "Test with context.",
        })
        predictor._client.chat.completions.create = AsyncMock(
            return_value=self._mock_response(content),
        )

        result = await predictor.predict(_make_qa_pairs())

        # ER override should force sev003 and include dept002
        assert result.severity == "sev003"
        assert "dept002" in result.departments
        # Context should be reset after predict()
        assert predictor._min_severity is None
        assert predictor._er_override is False

    @pytest.mark.asyncio
    async def test_predict_reprompts_on_fewer_than_3_diagnoses(self, predictor):
        """When LLM returns < 3 diagnoses, predict() re-prompts once."""
        # First response: only 2 diagnoses
        first_content = json.dumps({
            "diagnoses": [
                {"disease_id": "d001"},
                {"disease_id": "d002"},
            ],
            "departments": ["dept004"],
            "severity": "sev002",
            "reasoning": "Initial attempt.",
        })
        # Retry response: 4 diagnoses
        retry_content = json.dumps({
            "diagnoses": [
                {"disease_id": "d001"},
                {"disease_id": "d002"},
                {"disease_id": "d003"},
                {"disease_id": "d004"},
            ],
            "departments": ["dept004"],
            "severity": "sev002",
            "reasoning": "Expanded differentials.",
        })
        predictor._client.chat.completions.create = AsyncMock(
            side_effect=[
                self._mock_response(first_content),
                self._mock_response(retry_content),
            ],
        )

        result = await predictor.predict(_make_qa_pairs())

        # Should have called the API twice (initial + re-prompt)
        assert predictor._client.chat.completions.create.call_count == 2, (
            "Should re-prompt once when fewer than 3 diagnoses"
        )
        # Re-prompt message should ask for at least 3
        retry_call = predictor._client.chat.completions.create.call_args_list[1]
        retry_messages = retry_call.kwargs["messages"]
        assert len(retry_messages) == 4, (
            "Retry should have 4 messages: system + user + assistant + re-prompt"
        )
        assert "at least 3" in retry_messages[3]["content"], (
            "Re-prompt should ask for at least 3 diagnoses"
        )
        # Final result should use the retry response
        assert len(result.diagnoses) == 4
        assert result.diagnoses[0].disease_id == "d001"

    @pytest.mark.asyncio
    async def test_predict_accepts_retry_even_if_still_under_3(self, predictor):
        """If the retry still returns < 3, the result is accepted as-is."""
        content = json.dumps({
            "diagnoses": [{"disease_id": "d001"}],
            "departments": ["dept004"],
            "severity": "sev002",
            "reasoning": "Only one possible.",
        })
        predictor._client.chat.completions.create = AsyncMock(
            return_value=self._mock_response(content),
        )

        result = await predictor.predict(_make_qa_pairs())

        # Called twice (initial + re-prompt), but result accepted as-is
        assert predictor._client.chat.completions.create.call_count == 2
        assert len(result.diagnoses) == 1, (
            "After retry still < 3, result should be accepted as-is"
        )

    @pytest.mark.asyncio
    async def test_predict_no_reprompt_when_3_or_more(self, predictor):
        """When LLM returns >= 3 diagnoses, no re-prompt happens."""
        content = json.dumps({
            "diagnoses": [
                {"disease_id": "d001"},
                {"disease_id": "d002"},
                {"disease_id": "d003"},
            ],
            "departments": ["dept004"],
            "severity": "sev002",
            "reasoning": "Sufficient differentials.",
        })
        predictor._client.chat.completions.create = AsyncMock(
            return_value=self._mock_response(content),
        )

        result = await predictor.predict(_make_qa_pairs())

        assert predictor._client.chat.completions.create.call_count == 1, (
            "Should NOT re-prompt when >= 3 diagnoses returned"
        )
        assert len(result.diagnoses) == 3


# =====================================================================
# Prompt rendering tests
# =====================================================================

class TestPromptRendering:
    """Tests for PredictionPromptManager template rendering."""

    def test_system_prompt_is_lean(self, store):
        """System prompt is a concise role definition without reference tables."""
        pm = PredictionPromptManager(store)
        system = pm.render_system()

        assert "senior Thai physician" in system, (
            "System prompt should define the physician role"
        )
        # Reference tables should NOT be in the system prompt
        assert "d001" not in system, (
            "Disease table should be in the user prompt, not system"
        )
        assert "dept001" not in system, (
            "Department table should be in the user prompt, not system"
        )

    def test_user_prompt_contains_disease_table(self, store):
        """User prompt includes the disease reference table."""
        pm = PredictionPromptManager(store)
        prompt = pm.render_prompt(_make_qa_pairs())

        assert "d001" in prompt, "User prompt should contain disease ID d001"
        assert "Disease Reference" in prompt, (
            "User prompt should contain disease reference header"
        )

    def test_user_prompt_contains_department_table(self, store):
        """User prompt includes the department reference table."""
        pm = PredictionPromptManager(store)
        prompt = pm.render_prompt(_make_qa_pairs())

        assert "dept001" in prompt or "dept002" in prompt, (
            "User prompt should contain department IDs"
        )
        assert "Department Reference" in prompt, (
            "User prompt should contain department reference header"
        )

    def test_user_prompt_contains_severity_table(self, store):
        """User prompt includes the severity reference table."""
        pm = PredictionPromptManager(store)
        prompt = pm.render_prompt(_make_qa_pairs())

        assert "sev001" in prompt, "User prompt should contain severity ID sev001"
        assert "sev003" in prompt, "User prompt should contain severity ID sev003"
        assert "Severity Reference" in prompt, (
            "User prompt should contain severity reference header"
        )

    def test_user_prompt_groups_by_phase(self, store):
        """User prompt groups QA pairs by phase with headers."""
        pm = PredictionPromptManager(store)
        pairs = _make_qa_pairs()
        prompt = pm.render_prompt(pairs)

        assert "Phase 0" in prompt, "Should contain Phase 0 header"
        assert "Phase 1" in prompt, "Should contain Phase 1 header"
        assert "Phase 3" in prompt, "Should contain Phase 3 header"
        assert "Phase 4" in prompt, "Should contain Phase 4 header"

    def test_user_prompt_includes_llm_generated(self, store):
        """User prompt includes LLM-generated pairs under their own section."""
        pm = PredictionPromptManager(store)
        pairs = _make_qa_pairs()
        prompt = pm.render_prompt(pairs)

        assert "มียาที่ทานอยู่ไหม?" in prompt, (
            "Should contain LLM-generated question"
        )

    def test_user_prompt_with_min_severity(self, store):
        """User prompt includes min_severity instruction when set."""
        pm = PredictionPromptManager(store)
        prompt = pm.render_prompt([], min_severity="sev002_5")

        assert "sev002_5" in prompt, (
            "Should contain min_severity instruction"
        )

    def test_user_prompt_contains_min_diagnoses_guidance(self, store):
        """User prompt includes guidance about minimum 3 diagnoses."""
        pm = PredictionPromptManager(store)
        prompt = pm.render_prompt([])

        assert "at least 3" in prompt, (
            "User prompt should mention minimum 3 diagnoses"
        )
        assert "safety" in prompt.lower(), (
            "User prompt should mention patient safety"
        )

    def test_user_prompt_empty_pairs(self, store):
        """Empty QA pairs still render a valid prompt."""
        pm = PredictionPromptManager(store)
        prompt = pm.render_prompt([])
        assert "Instructions" in prompt, (
            "Should still contain the instructions section"
        )

    def test_group_by_phase_llm_goes_to_phase_8(self, store):
        """LLM-generated pairs (no phase) are grouped under phase 8."""
        pairs = _make_qa_pairs()
        grouped = PredictionPromptManager._group_by_phase(pairs)
        assert 8 in grouped, "LLM-generated pairs should be in phase 8"
        assert len(grouped[8]) == 1
