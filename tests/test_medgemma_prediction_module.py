"""Tests for MedgemmaPredictionModule and MedgemmaPromptManager.

Covers:
  - resolve_vllm_config: URL used as-is, empty VLLM_APIKEY → None, model fallback
  - __init__: Authorization header attached only when an API key is present
  - _strip_thinking: <unused94>…<unused95> block removal, no-block passthrough
  - _parse_response: XML extraction, name→ID mapping, unknown names omitted,
    case-insensitive disease fallback
  - _apply_safety_constraints: ER override, min severity enforcement
  - set_context: context stored and reset across predict()
  - Full predict() flow with a mocked httpx.AsyncClient
  - Transient errors (5xx / connection) → empty result; permanent (4xx) re-raised
  - MedgemmaPromptManager: system prompt option lists, instruction patient profile
"""

from unittest.mock import AsyncMock

import httpx
import pytest

from prescreen_rulesets.constants import VLLM_DEFAULT_MODEL, resolve_vllm_config
from prescreen_rulesets.models.pipeline import (
    DiagnosisResult,
    PredictionResult,
    QAPair,
)
from prescreen_rulesets.prediction.medgemma import MedgemmaPredictionModule
from prescreen_rulesets.prediction.prompt_manager import MedgemmaPromptManager
from prescreen_rulesets.ruleset import RulesetStore

_TEST_URL = "http://test-vllm:36000/v1/chat/completions"

# The documented example response — a silent reasoning block delimited by the
# <unused94>/<unused95> special tokens, followed by the XML answer.  These three
# names resolve to d020 / dept002 / sev003 in the v1 rulesets.
_EXAMPLE_CONTENT = (
    "<unused94>thought\n"
    "The patient presents with acute neurological deficits — facial droop, "
    "limb weakness, speech difficulty — pointing to a stroke.\n"
    "<unused95>"
    "<disease>Acute ischemic stroke and Transient Ischemic Attack</disease>\n"
    "<department>Emergency Medicine</department>\n"
    "<severity>Emergency</severity>"
)


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
def predictor(store: RulesetStore) -> MedgemmaPredictionModule:
    """Create a predictor with explicit config (skips env resolution)."""
    return MedgemmaPredictionModule(
        store=store,
        url=_TEST_URL,
        model="google/medgemma-27b-text-it",
        api_key="test-key",
    )


def _make_qa_pairs() -> list[QAPair]:
    """Build a representative set of QA pairs across phases."""
    return [
        QAPair(
            question="อายุ (ปี)", answer=38, source="rule_based",
            qid="demo_age", question_type="int", phase=0,
        ),
        QAPair(
            question="เพศกำเนิด", answer="Female", source="rule_based",
            qid="demo_gender", question_type="enum", phase=0,
        ),
        QAPair(
            question="หายใจลำบาก?", answer=False, source="rule_based",
            qid="emer_critical_1", question_type="yes_no", phase=1,
        ),
        QAPair(
            question="อาการหลัก", answer="Constipation", source="rule_based",
            qid="primary_symptom", question_type="single_select", phase=2,
        ),
        QAPair(
            question="มียาที่ทานอยู่ไหม?", answer="ไม่มี", source="llm_generated",
        ),
    ]


def _mock_response(
    content: str, status_code: int = 200, url: str = _TEST_URL,
) -> httpx.Response:
    """Build an httpx.Response shaped like a vLLM chat-completions reply."""
    return httpx.Response(
        status_code,
        json={"choices": [{"message": {"content": content}}]},
        request=httpx.Request("POST", url),
    )


# =====================================================================
# resolve_vllm_config tests
# =====================================================================

class TestVLLMConfigResolution:
    """Tests for VLLM_PREDICTOR_URL / VLLM_PREDICTOR_MODEL / VLLM_APIKEY parsing."""

    def test_url_used_as_is(self, monkeypatch):
        """VLLM_PREDICTOR_URL is returned verbatim — no /chat/completions stripping."""
        monkeypatch.setenv("VLLM_PREDICTOR_URL", _TEST_URL)
        assert resolve_vllm_config().url == _TEST_URL

    def test_empty_apikey_resolves_to_none(self, monkeypatch):
        """An empty VLLM_APIKEY parses as None (no Authorization header sent)."""
        monkeypatch.setenv("VLLM_APIKEY", "")
        assert resolve_vllm_config().api_key is None

    def test_unset_apikey_resolves_to_none(self, monkeypatch):
        """An unset VLLM_APIKEY parses as None."""
        monkeypatch.delenv("VLLM_APIKEY", raising=False)
        assert resolve_vllm_config().api_key is None

    def test_apikey_kept_when_set(self, monkeypatch):
        """A non-empty VLLM_APIKEY is kept as-is."""
        monkeypatch.setenv("VLLM_APIKEY", "secret-token")
        assert resolve_vllm_config().api_key == "secret-token"

    def test_model_fallback(self, monkeypatch):
        """An unset VLLM_PREDICTOR_MODEL falls back to the default model."""
        monkeypatch.delenv("VLLM_PREDICTOR_MODEL", raising=False)
        assert resolve_vllm_config().model == VLLM_DEFAULT_MODEL

    def test_no_auth_header_when_key_is_none(self, store):
        """When api_key is None, the connector sends no Authorization header."""
        pred = MedgemmaPredictionModule(store=store, url=_TEST_URL, api_key=None)
        assert "Authorization" not in pred._headers

    def test_auth_header_when_key_present(self, predictor):
        """When api_key is set, a Bearer Authorization header is built."""
        assert predictor._headers["Authorization"] == "Bearer test-key"

    def test_env_resolution_when_url_omitted(self, store, monkeypatch):
        """When url is None, url/model/api_key are resolved from the environment."""
        monkeypatch.setenv("VLLM_PREDICTOR_URL", _TEST_URL)
        monkeypatch.setenv("VLLM_PREDICTOR_MODEL", "google/medgemma-27b-text-it")
        monkeypatch.setenv("VLLM_APIKEY", "env-key")
        pred = MedgemmaPredictionModule(store=store)
        assert pred._url == _TEST_URL
        assert pred._model == "google/medgemma-27b-text-it"
        assert pred._headers["Authorization"] == "Bearer env-key"


# =====================================================================
# _strip_thinking tests
# =====================================================================

class TestStripThinking:
    """Tests for removal of the <unused94>…<unused95> reasoning block."""

    def test_strips_thinking_block(self, predictor):
        """Everything up to and including <unused95> is removed."""
        text = predictor._strip_thinking(_EXAMPLE_CONTENT)
        assert "<unused94>" not in text
        assert "<unused95>" not in text
        assert text.startswith("<disease>")

    def test_passthrough_when_no_token(self, predictor):
        """Content without a thinking block is returned unchanged."""
        plain = "<disease>Acne</disease><department>Dermatology</department>"
        assert predictor._strip_thinking(plain) == plain

    def test_takes_text_after_last_unused95(self, predictor):
        """When the token appears more than once, the last occurrence wins."""
        text = predictor._strip_thinking(
            "a<unused95>b<unused95><disease>X</disease>"
        )
        assert text == "<disease>X</disease>"


# =====================================================================
# _parse_response tests
# =====================================================================

class TestParseResponse:
    """Tests for XML parsing and name→ID resolution."""

    def test_example_response(self, predictor):
        """The documented example resolves to d020 / dept002 / sev003."""
        result = predictor._parse_response(_EXAMPLE_CONTENT)
        assert result.diagnoses == [DiagnosisResult(disease_id="d020")]
        assert result.departments == ["dept002"]
        assert result.severity == "sev003"

    def test_resolves_arbitrary_store_disease(self, predictor, store):
        """Any disease_name from the store maps back to its ID."""
        disease = next(iter(store.diseases.values()))
        content = (
            f"<disease>{disease.disease_name}</disease>"
            f"<department>Emergency Medicine</department>"
            f"<severity>Observe at Home</severity>"
        )
        result = predictor._parse_response(content)
        assert result.diagnoses == [DiagnosisResult(disease_id=disease.id)]
        assert result.severity == "sev001"

    def test_case_insensitive_disease_fallback(self, predictor):
        """A lowercased disease name still resolves via the CI fallback."""
        content = (
            "<disease>acute ischemic stroke and transient ischemic attack</disease>"
            "<department>Emergency Medicine</department>"
            "<severity>Emergency</severity>"
        )
        result = predictor._parse_response(content)
        assert result.diagnoses == [DiagnosisResult(disease_id="d020")]

    def test_unknown_disease_omitted(self, predictor):
        """An unrecognised disease name yields no diagnosis (logged, not raised)."""
        content = (
            "<disease>Not A Real Disease</disease>"
            "<department>Emergency Medicine</department>"
            "<severity>Emergency</severity>"
        )
        result = predictor._parse_response(content)
        assert result.diagnoses == []
        assert result.departments == ["dept002"]

    def test_unknown_department_omitted(self, predictor):
        """An unrecognised department name yields an empty departments list."""
        content = (
            "<disease>Acne</disease>"
            "<department>Made Up Department</department>"
            "<severity>Emergency</severity>"
        )
        result = predictor._parse_response(content)
        assert result.departments == []

    def test_unknown_severity_is_none(self, predictor):
        """An unrecognised severity name yields severity=None."""
        content = (
            "<disease>Acne</disease>"
            "<department>Dermatology</department>"
            "<severity>Somewhat Urgent</severity>"
        )
        result = predictor._parse_response(content)
        assert result.severity is None

    def test_no_tags_returns_empty(self, predictor):
        """Content without any answer tags returns an empty PredictionResult."""
        result = predictor._parse_response("the model produced no XML at all")
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
            diagnoses=[DiagnosisResult(disease_id="d001")],
            departments=["dept004"],
            severity="sev001",
        )
        result = predictor._apply_safety_constraints(
            parsed, er_override=True, min_severity=None,
        )
        assert result.severity == "sev003"
        assert "dept002" in result.departments

    def test_min_severity_enforcement(self, predictor):
        """When min_severity is set, a lower predicted severity is bumped up."""
        parsed = PredictionResult(
            diagnoses=[DiagnosisResult(disease_id="d001")],
            departments=["dept004"],
            severity="sev002",
        )
        result = predictor._apply_safety_constraints(
            parsed, er_override=False, min_severity="sev002_5",
        )
        assert result.severity == "sev002_5"

    def test_min_severity_no_bump_when_higher(self, predictor):
        """A predicted severity already above the floor is left untouched."""
        parsed = PredictionResult(
            diagnoses=[DiagnosisResult(disease_id="d001")],
            departments=["dept004"],
            severity="sev002",
        )
        result = predictor._apply_safety_constraints(
            parsed, er_override=False, min_severity="sev001",
        )
        assert result.severity == "sev002"

    def test_no_constraints(self, predictor):
        """With no constraints set, the result passes through unchanged."""
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
# Full predict() flow with mocked httpx client
# =====================================================================

class TestPredictFlow:
    """Integration tests for predict() with a mocked httpx.AsyncClient."""

    @pytest.mark.asyncio
    async def test_predict_success(self, predictor):
        """A successful call parses the XML answer into a PredictionResult."""
        predictor._client.post = AsyncMock(
            return_value=_mock_response(_EXAMPLE_CONTENT),
        )
        result = await predictor.predict(_make_qa_pairs())
        assert result.diagnoses == [DiagnosisResult(disease_id="d020")]
        assert result.departments == ["dept002"]
        assert result.severity == "sev003"

    @pytest.mark.asyncio
    async def test_predict_sends_expected_body_and_headers(self, predictor):
        """The request body mirrors the curl example; auth header is attached."""
        predictor._client.post = AsyncMock(
            return_value=_mock_response(_EXAMPLE_CONTENT),
        )
        await predictor.predict(_make_qa_pairs())

        call = predictor._client.post.call_args
        assert call.args[0] == _TEST_URL
        body = call.kwargs["json"]
        assert body["stream"] is False
        assert body["skip_special_tokens"] is False
        assert body["model"] == "google/medgemma-27b-text-it"
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["role"] == "user"
        assert call.kwargs["headers"]["Authorization"] == "Bearer test-key"

    @pytest.mark.asyncio
    async def test_predict_omits_auth_header_when_no_key(self, store):
        """A predictor built without an API key sends no Authorization header."""
        pred = MedgemmaPredictionModule(store=store, url=_TEST_URL, api_key=None)
        pred._client.post = AsyncMock(
            return_value=_mock_response(_EXAMPLE_CONTENT),
        )
        await pred.predict(_make_qa_pairs())
        assert "Authorization" not in pred._client.post.call_args.kwargs["headers"]

    @pytest.mark.asyncio
    async def test_predict_transient_5xx_returns_empty(self, predictor):
        """A 5xx response degrades gracefully to an empty PredictionResult."""
        predictor._client.post = AsyncMock(
            return_value=_mock_response("upstream error", status_code=503),
        )
        result = await predictor.predict(_make_qa_pairs())
        assert result.diagnoses == []
        assert result.departments == []
        assert result.severity is None

    @pytest.mark.asyncio
    async def test_predict_transient_connection_error_returns_empty(self, predictor):
        """A connection-level failure degrades gracefully to an empty result."""
        predictor._client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused"),
        )
        result = await predictor.predict(_make_qa_pairs())
        assert result.diagnoses == []

    @pytest.mark.asyncio
    async def test_predict_permanent_4xx_reraises(self, predictor):
        """A non-transient 4xx (e.g. 401 auth) surfaces to the caller."""
        predictor._client.post = AsyncMock(
            return_value=_mock_response("unauthorized", status_code=401),
        )
        with pytest.raises(httpx.HTTPStatusError):
            await predictor.predict(_make_qa_pairs())

    @pytest.mark.asyncio
    async def test_predict_with_context(self, predictor):
        """predict() with set_context applies the ER override and resets context."""
        predictor.set_context(er_override=True, min_severity="sev002")
        # Model predicts a low severity; ER override must force sev003 + dept002.
        content = (
            "<disease>Acne</disease>"
            "<department>Dermatology</department>"
            "<severity>Observe at Home</severity>"
        )
        predictor._client.post = AsyncMock(return_value=_mock_response(content))

        result = await predictor.predict(_make_qa_pairs())

        assert result.severity == "sev003"
        assert "dept002" in result.departments
        # Context is cleared after predict().
        assert predictor._min_severity is None
        assert predictor._er_override is False


# =====================================================================
# MedgemmaPromptManager rendering tests
# =====================================================================

class TestPromptRendering:
    """Tests for MedgemmaPromptManager template rendering."""

    def test_render_system_has_option_lists(self, store):
        """The system prompt carries the closed disease + department lists."""
        pm = MedgemmaPromptManager(store)
        system = pm.render_system()
        assert "- Emergency Medicine" in system
        # A known disease_name from the store appears in the option list.
        a_disease = next(iter(store.diseases.values())).disease_name
        assert f"- {a_disease}" in system

    def test_render_instruction_has_patient_profile(self, store):
        """The instruction prompt reflects demographics + conversation transcript."""
        pm = MedgemmaPromptManager(store)
        instruction = pm.render_instruction(_make_qa_pairs())
        assert "Age: 38" in instruction
        assert "Gender: Female" in instruction
        # The full transcript includes the LLM follow-up question.
        assert "มียาที่ทานอยู่ไหม?" in instruction
        # Presenting problem is filled from the primary_symptom qid.
        assert "Constipation" in instruction

    def test_render_instruction_empty_pairs(self, store):
        """Empty QA pairs still render — every slot falls back to 'N/A'."""
        pm = MedgemmaPromptManager(store)
        instruction = pm.render_instruction([])
        assert "Age: N/A" in instruction
        assert "## Conversation History\nN/A" in instruction
