"""Tests for prescreen_server backend selection.

Covers the ``app.py`` startup helpers that pick the LLM connectors from
environment variables:

  - ``_build_predictor``  — PREDICTOR_BACKEND: openai | medgemma | default | unknown
  - ``_build_generator``  — QUESTION_GENERATOR_BACKEND: openai | empty→None |
    legacy SKIP_GENERATOR | unknown
  - ``_openai_backend_selected`` — gates the conditional OPENAI_API_KEY check
"""

import pytest

from prescreen_rulesets.prediction import (
    MedgemmaPredictionModule,
    OpenAIPredictionModule,
)
from prescreen_rulesets.question_generator import OpenAIQuestionGenerator
from prescreen_rulesets.ruleset import RulesetStore
from prescreen_server.app import (
    _build_generator,
    _build_predictor,
    _openai_backend_selected,
)

_VLLM_URL = "http://test-vllm:36000/v1/chat/completions"


@pytest.fixture(scope="module")
def store() -> RulesetStore:
    """Load a real RulesetStore for testing."""
    s = RulesetStore()
    s.load()
    return s


@pytest.fixture(autouse=True)
def _clean_backend_env(monkeypatch):
    """Clear all backend-selection env vars before each test for isolation."""
    for var in (
        "PREDICTOR_BACKEND",
        "QUESTION_GENERATOR_BACKEND",
        "SKIP_GENERATOR",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "VLLM_PREDICTOR_URL",
    ):
        monkeypatch.delenv(var, raising=False)


# =====================================================================
# _build_predictor
# =====================================================================

class TestBuildPredictor:
    """PREDICTOR_BACKEND selection — a predictor is always required."""

    def test_default_is_openai(self, store, monkeypatch):
        """An unset PREDICTOR_BACKEND defaults to OpenAIPredictionModule."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        assert isinstance(_build_predictor(store), OpenAIPredictionModule)

    def test_explicit_openai(self, store, monkeypatch):
        """PREDICTOR_BACKEND=openai builds OpenAIPredictionModule."""
        monkeypatch.setenv("PREDICTOR_BACKEND", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        assert isinstance(_build_predictor(store), OpenAIPredictionModule)

    def test_medgemma(self, store, monkeypatch):
        """PREDICTOR_BACKEND=medgemma builds MedgemmaPredictionModule."""
        monkeypatch.setenv("PREDICTOR_BACKEND", "medgemma")
        monkeypatch.setenv("VLLM_PREDICTOR_URL", _VLLM_URL)
        assert isinstance(_build_predictor(store), MedgemmaPredictionModule)

    def test_case_and_whitespace_insensitive(self, store, monkeypatch):
        """Backend names are matched case-insensitively and stripped."""
        monkeypatch.setenv("PREDICTOR_BACKEND", "  MedGemma  ")
        monkeypatch.setenv("VLLM_PREDICTOR_URL", _VLLM_URL)
        assert isinstance(_build_predictor(store), MedgemmaPredictionModule)

    def test_unknown_backend_raises(self, store, monkeypatch):
        """An unrecognised PREDICTOR_BACKEND fails fast at startup."""
        monkeypatch.setenv("PREDICTOR_BACKEND", "bogus")
        with pytest.raises(RuntimeError, match="PREDICTOR_BACKEND"):
            _build_predictor(store)


# =====================================================================
# _build_generator
# =====================================================================

class TestBuildGenerator:
    """QUESTION_GENERATOR_BACKEND selection — may be disabled (None)."""

    def test_default_is_openai(self, monkeypatch):
        """An unset QUESTION_GENERATOR_BACKEND defaults to the OpenAI generator."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        assert isinstance(_build_generator(), OpenAIQuestionGenerator)

    def test_explicit_openai(self, monkeypatch):
        """QUESTION_GENERATOR_BACKEND=openai builds OpenAIQuestionGenerator."""
        monkeypatch.setenv("QUESTION_GENERATOR_BACKEND", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        assert isinstance(_build_generator(), OpenAIQuestionGenerator)

    def test_empty_disables_generator(self, monkeypatch):
        """An explicitly empty QUESTION_GENERATOR_BACKEND disables generation."""
        monkeypatch.setenv("QUESTION_GENERATOR_BACKEND", "")
        assert _build_generator() is None

    def test_legacy_skip_generator_flag(self, monkeypatch):
        """The legacy SKIP_GENERATOR=true flag still disables generation."""
        monkeypatch.setenv("SKIP_GENERATOR", "true")
        # Even with a valid backend selected, SKIP_GENERATOR wins.
        monkeypatch.setenv("QUESTION_GENERATOR_BACKEND", "openai")
        assert _build_generator() is None

    def test_unknown_backend_raises(self, monkeypatch):
        """An unrecognised non-empty QUESTION_GENERATOR_BACKEND fails fast."""
        monkeypatch.setenv("QUESTION_GENERATOR_BACKEND", "bogus")
        with pytest.raises(RuntimeError, match="QUESTION_GENERATOR_BACKEND"):
            _build_generator()


# =====================================================================
# _openai_backend_selected
# =====================================================================

class TestOpenAIBackendSelected:
    """Gates the conditional OPENAI_API_KEY / OPENROUTER_API_KEY startup check."""

    def test_default_requires_key(self):
        """Both backends default to openai → an API key is required."""
        assert _openai_backend_selected() is True

    def test_medgemma_predictor_openai_generator_requires_key(self, monkeypatch):
        """A medgemma predictor still needs a key while the generator is openai."""
        monkeypatch.setenv("PREDICTOR_BACKEND", "medgemma")
        assert _openai_backend_selected() is True

    def test_medgemma_predictor_disabled_generator_no_key(self, monkeypatch):
        """medgemma predictor + disabled generator → no OpenAI key needed."""
        monkeypatch.setenv("PREDICTOR_BACKEND", "medgemma")
        monkeypatch.setenv("QUESTION_GENERATOR_BACKEND", "")
        assert _openai_backend_selected() is False

    def test_medgemma_predictor_skip_generator_no_key(self, monkeypatch):
        """medgemma predictor + legacy SKIP_GENERATOR → no OpenAI key needed."""
        monkeypatch.setenv("PREDICTOR_BACKEND", "medgemma")
        monkeypatch.setenv("SKIP_GENERATOR", "true")
        assert _openai_backend_selected() is False
