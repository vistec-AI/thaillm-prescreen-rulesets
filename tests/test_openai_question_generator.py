"""Tests for OpenAIQuestionGenerator and its prompt manager.

Covers:
  - _filter_qa_pairs: phase 3 negative removal, other phases unchanged
  - _parse_response: valid JSON, fallback regex, fallback line-split, max cap
  - Prompt rendering: system and user templates render correctly
  - Full generate() flow with mocked OpenAI client
  - Transient error handling (graceful degradation)
  - Permanent error handling (re-raised)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from prescreen_rulesets.models.pipeline import GeneratedQuestions, QAPair
from prescreen_rulesets.question_generator.openai import OpenAIQuestionGenerator
from prescreen_rulesets.question_generator.prompt_manager import (
    QuestionGeneratorPromptManager,
)


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
    ]


# =====================================================================
# _filter_qa_pairs tests
# =====================================================================

class TestFilterQAPairs:
    """Tests for phase 3 negative-answer filtering."""

    def test_removes_phase3_false_answers(self):
        """Phase 3 entries with answer=False are excluded."""
        gen = OpenAIQuestionGenerator(api_key="test-key")
        pairs = _make_qa_pairs()
        filtered = gen._filter_qa_pairs(pairs)

        # The phase 3 False answer (emer_adult_abd2) should be removed
        phase3_qids = [p.qid for p in filtered if p.phase == 3]
        assert "emer_adult_abd2" not in phase3_qids, (
            "Phase 3 negative answer should be filtered out"
        )
        assert "emer_adult_abd1" in phase3_qids, (
            "Phase 3 positive answer should be kept"
        )

    def test_keeps_all_other_phases(self):
        """Non-phase-3 entries pass through regardless of answer value."""
        gen = OpenAIQuestionGenerator(api_key="test-key")
        pairs = _make_qa_pairs()
        filtered = gen._filter_qa_pairs(pairs)

        # Phase 1 has answer=False but should NOT be filtered (only phase 3)
        phase1_qids = [p.qid for p in filtered if p.phase == 1]
        assert "emer_critical_1" in phase1_qids, (
            "Phase 1 False answer should NOT be filtered"
        )

    def test_empty_input(self):
        """Empty input returns empty output."""
        gen = OpenAIQuestionGenerator(api_key="test-key")
        assert gen._filter_qa_pairs([]) == []


# =====================================================================
# _parse_response tests
# =====================================================================

class TestParseResponse:
    """Tests for LLM response parsing with fallbacks."""

    def setup_method(self):
        self.gen = OpenAIQuestionGenerator(api_key="test-key", max_questions=5)

    def test_valid_json_object(self):
        """Standard JSON object with questions key."""
        content = '{"questions": ["Q1", "Q2", "Q3"]}'
        result = self.gen._parse_response(content)
        assert result == ["Q1", "Q2", "Q3"]

    def test_json_with_extra_keys(self):
        """JSON object with extra keys — questions still extracted."""
        content = '{"questions": ["Q1"], "reasoning": "some text"}'
        result = self.gen._parse_response(content)
        assert result == ["Q1"]

    def test_max_questions_cap(self):
        """Result is capped at max_questions."""
        questions = [f"Q{i}" for i in range(20)]
        content = f'{{"questions": {questions}}}'.replace("'", '"')
        result = self.gen._parse_response(content)
        assert len(result) == 5, (
            f"Expected 5 questions (max_questions), got {len(result)}"
        )

    def test_fallback_json_array(self):
        """Regex fallback extracts a bare JSON array from text."""
        content = 'Here are questions: ["Q1", "Q2"]'
        result = self.gen._parse_response(content)
        assert result == ["Q1", "Q2"]

    def test_fallback_line_split(self):
        """Line-split fallback when no valid JSON is found."""
        content = "Question 1\nQuestion 2\n\nQuestion 3"
        result = self.gen._parse_response(content)
        assert result == ["Question 1", "Question 2", "Question 3"]

    def test_empty_string(self):
        """Empty response returns empty list."""
        assert self.gen._parse_response("") == []

    def test_filters_non_string_entries(self):
        """Non-string entries in the questions array are dropped."""
        content = '{"questions": ["Q1", 42, null, "Q2"]}'
        result = self.gen._parse_response(content)
        assert result == ["Q1", "Q2"]

    def test_filters_blank_strings(self):
        """Blank strings in the questions array are dropped."""
        content = '{"questions": ["Q1", "  ", "", "Q2"]}'
        result = self.gen._parse_response(content)
        assert result == ["Q1", "Q2"]


# =====================================================================
# Prompt rendering tests
# =====================================================================

class TestPromptRendering:
    """Tests for QuestionGeneratorPromptManager template rendering."""

    def test_system_prompt_renders(self):
        """System prompt renders without errors and contains key content."""
        pm = QuestionGeneratorPromptManager()
        system = pm.render_system()
        assert "Thai" in system or "Thai" in system.lower(), (
            "System prompt should mention Thai language"
        )
        assert "questions" in system, (
            "System prompt should mention the response format"
        )

    def test_user_prompt_groups_by_phase(self):
        """User prompt groups QA pairs by phase with headers."""
        pm = QuestionGeneratorPromptManager()
        pairs = _make_qa_pairs()
        prompt = pm.render_prompt(pairs)

        assert "Phase 0" in prompt, "Should contain Phase 0 header"
        assert "Phase 1" in prompt, "Should contain Phase 1 header"
        assert "Phase 3" in prompt, "Should contain Phase 3 header"
        assert "Phase 4" in prompt, "Should contain Phase 4 header"

    def test_user_prompt_contains_qa_content(self):
        """User prompt includes question text and serialized answers."""
        pm = QuestionGeneratorPromptManager()
        pairs = _make_qa_pairs()
        prompt = pm.render_prompt(pairs)

        # Check that Thai question text appears
        assert "อายุ" in prompt, "Should contain the age question"
        assert "ท้องน้อยด้านขวา" in prompt, (
            "Should contain the Thai free-text answer"
        )

    def test_user_prompt_empty_pairs(self):
        """Empty QA pairs still render a valid prompt."""
        pm = QuestionGeneratorPromptManager()
        prompt = pm.render_prompt([])
        assert "follow-up questions" in prompt, (
            "Should still contain the closing instruction"
        )

    def test_group_by_phase(self):
        """_group_by_phase returns sorted dict keyed by phase number."""
        pairs = _make_qa_pairs()
        grouped = QuestionGeneratorPromptManager._group_by_phase(pairs)
        assert list(grouped.keys()) == [0, 1, 3, 4], (
            "Should have phases 0, 1, 3, 4 in order"
        )
        assert len(grouped[0]) == 2, "Phase 0 should have 2 pairs"
        assert len(grouped[3]) == 2, "Phase 3 should have 2 pairs"


# =====================================================================
# Full generate() flow with mocked OpenAI client
# =====================================================================

class TestGenerateFlow:
    """Integration tests for generate() with mocked AsyncOpenAI."""

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """Successful API call returns parsed questions."""
        gen = OpenAIQuestionGenerator(api_key="test-key")

        # Mock the OpenAI response
        mock_message = MagicMock()
        mock_message.content = '{"questions": ["ปวดมานานแค่ไหน?", "มียาที่ทานอยู่ไหม?"]}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        gen._client.chat.completions.create = AsyncMock(return_value=mock_response)

        pairs = _make_qa_pairs()
        result = await gen.generate(pairs)

        assert isinstance(result, GeneratedQuestions)
        assert len(result.questions) == 2
        assert "ปวดมานานแค่ไหน?" in result.questions

    @pytest.mark.asyncio
    async def test_generate_filters_before_sending(self):
        """Phase 3 negative answers are filtered before the API call."""
        gen = OpenAIQuestionGenerator(api_key="test-key")

        mock_message = MagicMock()
        mock_message.content = '{"questions": ["follow up"]}'
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        gen._client.chat.completions.create = AsyncMock(return_value=mock_response)

        pairs = _make_qa_pairs()
        await gen.generate(pairs)

        # Inspect the user prompt sent to the API — phase 3 negative
        # answer qid should not appear in the rendered prompt
        call_args = gen._client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "emer_adult_abd2" not in user_msg, (
            "Phase 3 negative answer qid should not appear in the prompt"
        )

    @pytest.mark.asyncio
    async def test_generate_transient_error_returns_empty(self):
        """Transient API errors return empty questions (graceful degradation)."""
        import openai as openai_mod

        gen = OpenAIQuestionGenerator(api_key="test-key")
        gen._client.chat.completions.create = AsyncMock(
            side_effect=openai_mod.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body=None,
            ),
        )

        result = await gen.generate(_make_qa_pairs())
        assert result.questions == [], (
            "Transient error should return empty questions"
        )

    @pytest.mark.asyncio
    async def test_generate_auth_error_reraises(self):
        """Permanent errors (auth) are re-raised to the caller."""
        import openai as openai_mod

        gen = OpenAIQuestionGenerator(api_key="bad-key")
        gen._client.chat.completions.create = AsyncMock(
            side_effect=openai_mod.AuthenticationError(
                message="invalid api key",
                response=MagicMock(status_code=401, headers={}),
                body=None,
            ),
        )

        with pytest.raises(openai_mod.AuthenticationError):
            await gen.generate(_make_qa_pairs())

    @pytest.mark.asyncio
    async def test_generate_empty_content(self):
        """Empty API response content returns empty questions."""
        gen = OpenAIQuestionGenerator(api_key="test-key")

        mock_message = MagicMock()
        mock_message.content = ""
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        gen._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await gen.generate(_make_qa_pairs())
        assert result.questions == []
