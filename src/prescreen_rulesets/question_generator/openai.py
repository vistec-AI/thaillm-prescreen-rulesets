"""OpenAIQuestionGenerator — concrete QuestionGenerator using OpenAI API.

Uses ``openai.AsyncOpenAI`` to call the chat completions endpoint with
JSON mode, then parses the response into a list of follow-up questions.

Transient errors (rate limit, timeout, connection) degrade gracefully by
returning an empty question list.  Permanent errors (auth, invalid model)
are re-raised so callers can fix their configuration.
"""

from __future__ import annotations

import json
import logging
import re

import openai

from prescreen_rulesets.interfaces import QuestionGenerator
from prescreen_rulesets.models.pipeline import GeneratedQuestions, QAPair
from prescreen_rulesets.question_generator.prompt_manager import (
    QuestionGeneratorPromptManager,
)

logger = logging.getLogger(__name__)


class OpenAIQuestionGenerator(QuestionGenerator):
    """LLM-backed question generator using the OpenAI chat completions API.

    Args:
        api_key: API key.  When ``None``, resolved from environment variables:
            ``OPENAI_API_KEY`` first, then ``OPENROUTER_API_KEY`` as fallback.
        base_url: Base URL override for OpenAI-compatible endpoints.
            Auto-set when falling back to OpenRouter.
        model: Model identifier to use for chat completions.
        temperature: Sampling temperature (0-2).  ``None`` (default) omits the
            parameter, letting the API use its model-specific default.
        max_tokens: Maximum tokens in the completion response.  ``None``
            (default) omits the parameter — some models (e.g. reasoning
            models) don't support ``max_tokens``.
        max_questions: Hard cap on the number of returned questions (default 5).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-5.4",
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_questions: int = 5,
    ) -> None:
        # When no explicit api_key is provided, resolve the provider from
        # environment variables.  Priority: OPENAI_API_KEY > OPENROUTER_API_KEY.
        # OpenRouter requires a base_url override and a provider-prefixed model.
        if api_key is None and base_url is None:
            from prescreen_rulesets.constants import resolve_llm_config
            config = resolve_llm_config(model)
            api_key = config.api_key
            base_url = config.base_url
            model = config.model
            if config.provider != "none":
                logger.info("QuestionGenerator using %s provider", config.provider)

        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_questions = max_questions
        self._prompt_manager = QuestionGeneratorPromptManager()

    async def generate(self, qa_pairs: list[QAPair]) -> GeneratedQuestions:
        """Generate follow-up questions from rule-based QA history.

        Filters the QA pairs, renders prompts via the prompt manager,
        calls the OpenAI API, and parses the response into questions.

        Returns an empty ``GeneratedQuestions`` on transient API errors
        so the pipeline can continue without LLM follow-ups.
        """
        filtered = self._filter_qa_pairs(qa_pairs)

        system_prompt = self._prompt_manager.render_system()
        user_prompt = self._prompt_manager.render_prompt(filtered)

        try:
            # Build kwargs dynamically — some models (e.g. reasoning models)
            # reject unsupported params like max_tokens or temperature.
            kwargs: dict = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
            }
            if self._temperature is not None:
                kwargs["temperature"] = self._temperature
            if self._max_tokens is not None:
                kwargs["max_tokens"] = self._max_tokens
            response = await self._client.chat.completions.create(**kwargs)
        except (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
        ) as exc:
            # Transient errors — degrade gracefully
            logger.warning(
                "OpenAI transient error during question generation: %s", exc,
            )
            return GeneratedQuestions(questions=[])

        # Permanent errors (AuthenticationError, NotFoundError, etc.)
        # propagate to the caller so they can fix configuration.

        content = response.choices[0].message.content or ""
        questions = self._parse_response(content)
        return GeneratedQuestions(questions=questions)

    def _filter_qa_pairs(self, qa_pairs: list[QAPair]) -> list[QAPair]:
        """Filter QA pairs before sending to the LLM.

        Phase 3 (ER Checklist) entries where ``answer is False`` are removed
        because only positive findings are diagnostically relevant for the
        LLM.  All other phases pass through unchanged.
        """
        filtered: list[QAPair] = []
        for pair in qa_pairs:
            # Phase 3 negative answers (answer is exactly False) are noise
            # for the LLM — the patient doesn't have that ER symptom.
            if pair.phase == 3 and pair.answer is False:
                continue
            filtered.append(pair)
        return filtered

    def _parse_response(self, content: str) -> list[str]:
        """Parse the LLM response into a list of question strings.

        Expected format: ``{"questions": ["...", "..."]}``.
        Fallbacks:
          1. Regex extraction of a JSON array from the response
          2. Line-split (one question per non-empty line)

        The result is capped at ``max_questions``.
        """
        # Primary: parse as JSON object with "questions" key
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "questions" in data:
                questions = data["questions"]
                if isinstance(questions, list):
                    result = [q for q in questions if isinstance(q, str) and q.strip()]
                    return result[: self._max_questions]
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback 1: extract a JSON array from the response text
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            try:
                arr = json.loads(match.group())
                if isinstance(arr, list):
                    result = [q for q in arr if isinstance(q, str) and q.strip()]
                    return result[: self._max_questions]
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback 2: treat each non-empty line as a question
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return lines[: self._max_questions]
